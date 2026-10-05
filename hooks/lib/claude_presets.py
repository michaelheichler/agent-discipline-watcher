"""Split from the settings writer, because rendering a preset and persisting one are separate concerns."""
from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path
from typing import Any

PRESETS = ("mixed", "luna")
CLAUDE_SONNET_MODEL = "claude-sonnet-5-5"
MANAGED_MARKER = "adw-managed-hook-v1"
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"
SONNET_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_sonnet.sh"
HANDLER_TIMEOUT = 120


def validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly mixed or luna")
    return value


def _command(handler: Path) -> str:
    return f"ADW_CLAUDE_MANAGED={MANAGED_MARKER} {shlex.quote(str(handler))}"


def luna_command() -> str:
    return _command(LUNA_HANDLER_PATH)


def sonnet_command() -> str:
    return _command(SONNET_HANDLER_PATH)


def is_managed_hook(value: object) -> bool:
    """Recognised by marker, because a retired agent hook carries a prompt where a command hook carries a command."""
    if not isinstance(value, dict):
        return False
    if value.get("type") == "agent":
        prompt = value.get("prompt")
        return isinstance(prompt, str) and prompt.splitlines()[:1] == [MANAGED_MARKER]
    if value.get("type") != "command":
        return False
    command = value.get("command")
    if not isinstance(command, str):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return (
        len(parts) == 2
        and parts[0] == f"ADW_CLAUDE_MANAGED={MANAGED_MARKER}"
        and Path(parts[1]).is_absolute()
    )


def hook_entries(settings: object) -> list[tuple[str, object]]:
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks"), dict):
        return []
    return [
        (lifecycle, hook)
        for lifecycle, groups in settings["hooks"].items()
        if isinstance(lifecycle, str) and isinstance(groups, list)
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("hooks"), list)
        for hook in group["hooks"]
    ]


def managed_hooks(settings: object) -> dict[str, list[object]]:
    managed: dict[str, list[object]] = {}
    for lifecycle, hook in hook_entries(settings):
        if is_managed_hook(hook):
            managed.setdefault(lifecycle, []).append(hook)
    return managed


def has_retired_agent_hook(settings: object) -> bool:
    """Retired, because a tool-less agent hook cannot run the journal helper its prompt names."""
    return any(
        isinstance(hook, dict) and hook.get("type") == "agent" and is_managed_hook(hook)
        for _lifecycle, hook in hook_entries(settings)
    )


def managed_hash(settings: object) -> str:
    payload = json.dumps(managed_hooks(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preset_managed_hash(preset: str | None) -> str:
    return managed_hash({"hooks": generated_hooks(preset) if preset in PRESETS else {}})


def _kept_group(group: object) -> object | None:
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return group
    remaining = [hook for hook in group["hooks"] if not is_managed_hook(hook)]
    if len(remaining) == len(group["hooks"]):
        return group
    return {**group, "hooks": remaining} if remaining else None


def without_managed(settings: dict[str, Any]) -> dict[str, Any]:
    """Only our own entries go, because a lifecycle the user filled is not ours to empty."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    cleaned_hooks: dict[str, Any] = dict(hooks)
    for lifecycle, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        kept = [group for group in (_kept_group(entry) for entry in groups) if group is not None]
        if kept:
            cleaned_hooks[lifecycle] = kept
        else:
            cleaned_hooks.pop(lifecycle, None)
    return {**settings, "hooks": cleaned_hooks}


def _handler(command: str) -> dict[str, Any]:
    return {"type": "command", "command": command, "timeout": HANDLER_TIMEOUT}


def _preset_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    """Luna also reads live comments on PostToolUse, because only its handler judges them per write."""
    if preset == "luna":
        handler = _handler(luna_command())
        return {
            "PostToolUse": [{"matcher": WRITE_MATCHER, "hooks": [handler]}],
            "Stop": [{"hooks": [handler]}],
        }
    return {"Stop": [{"hooks": [_handler(sonnet_command())]}]}


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    return _preset_hooks(validate_preset(preset))
