"""Split from the settings writer, because rendering a preset and persisting one are separate concerns."""
from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path
from typing import Any

PRESETS = ("haiku", "mixed", "luna", "luna-native")
CLAUDE_HAIKU_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_SONNET_MODEL = "claude-sonnet-4-6"
LUNA_NATIVE_MODEL = "luna"
MANAGED_MARKER = "adw-managed-hook-v1"
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"
JOURNAL_READER_PATH = shlex.quote(str(PLUGIN_ROOT / "hooks" / "read_claude_journal.sh"))
HANDLER_TIMEOUT = 120
STRUCTURED_OUTPUT_CONTRACT = (
    "OUTPUT CONTRACT. Use the native StructuredOutput tool exactly once at the end of the review. "
    "Pass one object in exactly one of these two shapes.\n"
    "{\"ok\": true}\n"
    "{\"ok\": false, \"reason\": \"one remediation instruction under 200 characters\"}\n"
    "Do not return the object as plain text. Do not add an output label or any prose after the tool call.\n"
)


def validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly haiku, mixed, luna, or luna-native")
    return value


def model_for(preset: str, role: str) -> str:
    """luna-native names a model the harness injects, because LeverFrame puts Luna in the Claude model list."""
    if preset == "mixed":
        return CLAUDE_HAIKU_MODEL if role == "comment" else CLAUDE_SONNET_MODEL
    if preset == "haiku":
        return CLAUDE_HAIKU_MODEL
    if preset == "luna-native":
        return LUNA_NATIVE_MODEL
    raise ValueError("luna uses command handlers, not a native model")


def luna_command() -> str:
    return f"ADW_CLAUDE_MANAGED={MANAGED_MARKER} {shlex.quote(str(LUNA_HANDLER_PATH))}"


def comment_prompt(preset: str) -> str:
    validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's post-write comment verifier.\n"
        "Matching hooks run in parallel. Inspect only the just-written eligible file named by this raw host event; "
        "do not expect another hook to have prepared context and do not duplicate the raw event content. "
        "Use read-only inspection. Do not edit files, settings, or unrelated paths.\n"
        "Parse the hook input supplied after this prompt. If it is empty, malformed, unrelated to a write, "
        "or has no ADW candidate, use the successful StructuredOutput shape.\n"
        "Do not deny or undo the completed write.\n"
        + STRUCTURED_OUTPUT_CONTRACT
        + "Hook input: $ARGUMENTS"
    )


def stop_prompt(preset: str) -> str:
    validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's Stop verifier.\n"
        "Check stop_hook_active before doing any work. If it is true, skip every remaining step and "
        "use the successful StructuredOutput shape. "
        f"Read only the current session's bounded ADW candidate journal by running the exact helper {JOURNAL_READER_PATH} "
        "with the session_id from this hook input as its sole argument. Do not open state files directly, scan "
        "unrelated files, or read files not named by the helper output. "
        "Use read-only inspection. Do not scan unrelated files or edit files or settings.\n"
        "Batch all current prose and document candidates in one review. Empty or malformed ADW-owned input "
        "uses the successful StructuredOutput shape. A clean review uses the same shape. A failed review uses "
        "the failure shape below.\n"
        "Use the session_id from this hook input to locate only its journal.\n"
        + STRUCTURED_OUTPUT_CONTRACT
        + "Hook input: $ARGUMENTS"
    )


def is_managed_hook(value: object) -> bool:
    """Recognised by marker, because an agent hook carries a prompt where a command hook carries a command."""
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


def managed_hooks(settings: object) -> dict[str, list[object]]:
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks"), dict):
        return {}
    managed: dict[str, list[object]] = {}
    for lifecycle, groups in settings["hooks"].items():
        if not isinstance(lifecycle, str) or not isinstance(groups, list):
            continue
        entries = [
            hook
            for group in groups
            if isinstance(group, dict) and isinstance(group.get("hooks"), list)
            for hook in group["hooks"]
            if is_managed_hook(hook)
        ]
        if entries:
            managed[lifecycle] = entries
    return managed


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


def _agent(model: str, prompt: str) -> dict[str, Any]:
    return {"type": "agent", "model": model, "timeout": HANDLER_TIMEOUT, "prompt": prompt}


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    selected = validate_preset(preset)
    if selected == "luna":
        handler = {"type": "command", "command": luna_command(), "timeout": HANDLER_TIMEOUT}
        comment, document = handler, handler
    else:
        comment = _agent(model_for(selected, "comment"), comment_prompt(selected))
        document = _agent(model_for(selected, "document"), stop_prompt(selected))
    return {
        "PostToolUse": [{"matcher": WRITE_MATCHER, "hooks": [comment]}],
        "Stop": [{"hooks": [document]}],
    }
