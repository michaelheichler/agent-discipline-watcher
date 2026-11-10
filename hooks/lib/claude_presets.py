"""Split from the settings writer, because rendering a preset and persisting one are separate concerns."""
from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path

try:
    from . import config_roots as config_paths
except ImportError:
    import config_roots as config_paths
from typing import Any

PRESETS = ("luna",)
RETIRED_HANDLER = "claude_sonnet.sh"
MANAGED_MARKER = "adw-managed-hook-v1"
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
STABLE_ROOT = config_paths.install_root(Path("."))
CACHE_PARTS = ("plugins", "cache")
HANDLER_TIMEOUT = 120


def validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly luna")
    return value


def handler_root() -> Path:
    """The stable install, because a plugin cache revision vanishes on update."""
    if PLUGIN_ROOT.parts[-5:-3] != CACHE_PARTS:
        return PLUGIN_ROOT
    stable = config_paths.install_root()
    return stable if (stable / "hooks" / "claude_luna.sh").is_file() else PLUGIN_ROOT


def _command(leaf: str) -> str:
    handler = handler_root() / "hooks" / leaf
    return f"ADW_CLAUDE_MANAGED={MANAGED_MARKER} {shlex.quote(str(handler))}"


def luna_command() -> str:
    return _command("claude_luna.sh")


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


def _is_retired_hook(hook: object) -> bool:
    """Retired, because an agent hook has no tools and the Sonnet handler ran headless Claude."""
    if not isinstance(hook, dict) or not is_managed_hook(hook):
        return False
    return hook.get("type") == "agent" or Path(shlex.split(hook["command"])[-1]).name == RETIRED_HANDLER


def has_retired_hook(settings: object) -> bool:
    return any(_is_retired_hook(hook) for _lifecycle, hook in hook_entries(settings))


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


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    """Luna also reads live comments on PostToolUse, because only its handler judges them per write."""
    validate_preset(preset)
    handler = _handler(luna_command())
    return {
        "PostToolUse": [{"matcher": WRITE_MATCHER, "hooks": [handler]}],
        "Stop": [{"hooks": [handler]}],
    }
