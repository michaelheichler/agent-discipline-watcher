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
AGENT_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|AskUserQuestion"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PLUGIN_ROOT / "hooks" / "hooks.json"
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"
JOURNAL_READER_PATH = shlex.quote(str(PLUGIN_ROOT / "hooks" / "read_claude_journal.sh"))
SHIPPED_READER_PATH = "\"${CLAUDE_PLUGIN_ROOT}\"/hooks/read_claude_journal.sh"
SHIPPED_PRESET = "haiku"
SUPERSEDED_FLAG = "--superseded"
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


def _numbered(steps: list[str]) -> str:
    return "".join(f"{index}. {step}\n" for index, step in enumerate(steps, start=1))


def _yield_steps(preset: str) -> list[str]:
    """Only the shipped reviewer yields, because a preset entry is the replacement."""
    if preset != SHIPPED_PRESET:
        return []
    return [
        f"Run this exact helper with {SUPERSEDED_FLAG} as its only argument: {SHIPPED_READER_PATH}. "
        "When it prints true, a configured preset replaces this reviewer, so skip every remaining step "
        "and use the successful StructuredOutput shape."
    ]


def _reader_path(preset: str) -> str:
    return SHIPPED_READER_PATH if preset == SHIPPED_PRESET else JOURNAL_READER_PATH


def comment_prompt(preset: str) -> str:
    steps = [
        *_yield_steps(validate_preset(preset)),
        "Read the named path.",
        "Judge only what deterministic rules cannot decide, meaning reader-facing English and the intent "
        "behind a comment. Text a question puts to the user counts as reader-facing English.",
        "Choose one output shape below.",
    ]
    return (
        f"{MANAGED_MARKER}\n"
        "Review one completed write for reader-facing English and comment discipline.\n\n"
        "SCOPE. Inspect only the path named in the hook input. Read only. Never edit a file, never change "
        "a setting, never undo the write that already landed.\n\n"
        "STEPS, in order.\n" + _numbered(steps) + "\n"
        + STRUCTURED_OUTPUT_CONTRACT + "\n"
        "FAILURE MODE TO AVOID. Emit no prose, no preamble, no explanation, no markdown fence. A reply that "
        "opens with wording such as \"The answer is\" fails this hook and denies nothing, so it wastes the call. "
        "When the input is empty, malformed, unrelated to a write, or carries no candidate, use the successful "
        "StructuredOutput shape. When uncertain, use the successful StructuredOutput shape.\n\n"
        "Hook input: $ARGUMENTS"
    )


def stop_prompt(preset: str) -> str:
    selected = validate_preset(preset)
    steps = [
        "Read stop_hook_active in the hook input. When it is true, skip every remaining step and use the "
        "successful StructuredOutput shape.",
        *_yield_steps(selected),
        "Run this exact helper with the session_id from the hook input as its only argument: "
        + _reader_path(selected),
        "Batch all prose and document candidates the helper returns into one judgement rather than one call each.",
        "Choose one output shape below.",
    ]
    return (
        f"{MANAGED_MARKER}\n"
        "Review one finished turn for reader-facing English across every candidate it produced.\n\n"
        "SCOPE. Read only what the journal helper names. Never open a state file directly, never read a path "
        "the helper output does not list, never edit anything.\n\n"
        "STEPS, in order.\n" + _numbered(steps) + "\n"
        + STRUCTURED_OUTPUT_CONTRACT + "\n"
        "FAILURE MODE TO AVOID. Emit no prose, no preamble, no explanation, no markdown fence. When the helper "
        "returns nothing, when the input is malformed, or when uncertain, use the successful StructuredOutput shape.\n\n"
        "Hook input: $ARGUMENTS"
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


def supersedes_plugin(settings: object) -> bool:
    """Judged by the yield step, because an installer copy of the shipped entry carries it too."""
    return any(
        SUPERSEDED_FLAG not in str(hook.get("prompt") or hook.get("command") or "")
        for entries in managed_hooks(settings).values()
        for hook in entries
        if isinstance(hook, dict)
    )


def plugin_superseded(settings_path: Path) -> bool:
    """False on a bad read, because a skipped reviewer is worse than a doubled one."""
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return supersedes_plugin(settings)


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


def _preset_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    if preset == "luna":
        handler = {"type": "command", "command": luna_command(), "timeout": HANDLER_TIMEOUT}
        comment, document, matcher = handler, handler, WRITE_MATCHER
    else:
        comment = _agent(model_for(preset, "comment"), comment_prompt(preset))
        document = _agent(model_for(preset, "document"), stop_prompt(preset))
        matcher = AGENT_MATCHER
    return {
        "PostToolUse": [{"matcher": matcher, "hooks": [comment]}],
        "Stop": [{"hooks": [document]}],
    }


def shipped_hooks() -> dict[str, list[dict[str, Any]]]:
    return _preset_hooks(SHIPPED_PRESET)


def _is_agent_group(group: object) -> bool:
    entries = group.get("hooks") if isinstance(group, dict) else None
    return isinstance(entries, list) and any(isinstance(entry, dict) and entry.get("type") == "agent" for entry in entries)


def render_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Rendered from the preset, because a hand-kept copy drifted."""
    hooks = dict(manifest["hooks"])
    for lifecycle, groups in shipped_hooks().items():
        kept = [group for group in hooks.get(lifecycle, []) if not _is_agent_group(group)]
        hooks[lifecycle] = kept + groups
    return {**manifest, "hooks": hooks}


def main() -> int:
    current = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    MANIFEST_PATH.write_text(json.dumps(render_manifest(current), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    """Empty for the shipped preset, because the plugin manifest already runs it."""
    selected = validate_preset(preset)
    return {} if selected == SHIPPED_PRESET else _preset_hooks(selected)
