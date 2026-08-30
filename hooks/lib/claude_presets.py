"""Split from the settings writer, because rendering a preset and persisting one are separate concerns."""
from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

PRESETS = ("haiku", "mixed", "luna", "luna-native")
LUNA_NATIVE_MODEL = "luna"
MANAGED_MARKER = "adw-managed-hook-v1"
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"
JOURNAL_READER_PATH = shlex.quote(str(PLUGIN_ROOT / "hooks" / "read_claude_journal.sh"))
HANDLER_TIMEOUT = 120


def validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly haiku, mixed, luna, or luna-native")
    return value


def model_for(preset: str, role: str) -> str:
    """luna-native names a model the harness injects, because LeverFrame puts Luna in the Claude model list."""
    if preset == "mixed":
        return "haiku" if role == "comment" else "sonnet"
    if preset == "haiku":
        return "haiku"
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
        "or has no ADW candidate, return exactly {\"ok\": true}.\n"
        "A successful check returns exactly {\"ok\": true}. A failed check returns {\"ok\": false, "
        "\"reason\": \"one bounded remediation instruction\"}.\n"
        "Do not deny or undo the completed write.\n"
        "Hook input: $ARGUMENTS"
    )


def stop_prompt(preset: str) -> str:
    validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's Stop verifier.\n"
        "Check stop_hook_active before doing any work. If it is true, return exactly {\"ok\": true}. "
        f"Read only the current session's bounded ADW candidate journal by running the exact helper {JOURNAL_READER_PATH} "
        "with the session_id from this hook input as its sole argument. Do not open state files directly, scan "
        "unrelated files, or read files not named by the helper output. "
        "Use read-only inspection. Do not scan unrelated files or edit files or settings.\n"
        "Batch all current prose and document candidates in one review. Empty or malformed ADW-owned input "
        "returns exactly {\"ok\": true}. A clean review returns exactly {\"ok\": true}. A failed review "
        "returns {\"ok\": false, \"reason\": \"one bounded remediation instruction\"}.\n"
        "Use the session_id from this hook input to locate only its journal.\n"
        "Hook input: $ARGUMENTS"
    )


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
