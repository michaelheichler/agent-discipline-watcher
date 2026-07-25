"""Typed accessors over Claude Code hook event payloads."""

from __future__ import annotations

_TOOL_INPUT_KEYS = ("tool_input", "toolInput", "input")
_FILE_PATH_KEYS = ("file_path", "path")
_PROMPT_KEYS = ("prompt", "user_prompt")
_TASK_SUBJECT_KEYS = ("task_subject", "task_name")


def _tool_input(payload: dict) -> dict:
    """Resolve the tool-arguments slot tolerating the three observed key names."""
    for key in _TOOL_INPUT_KEYS:
        value = payload.get(key)
        # because pre_write.py or-chains and skips an empty dict, this must agree
        if isinstance(value, dict) and value:
            return value
    return {}


def session_id(payload: dict) -> str:
    """Return the session id, or '' when absent."""
    value = payload.get("session_id")
    return value if isinstance(value, str) else ""


def cwd(payload: dict) -> str:
    """Return the working directory the hook ran in, or '' when absent."""
    value = payload.get("cwd")
    return value if isinstance(value, str) else ""


def tool_name(payload: dict) -> str:
    """Return the tool name for a Pre/PostToolUse or failure event, or ''."""
    value = payload.get("tool_name")
    return value if isinstance(value, str) else ""


def tool_use_id(payload: dict) -> str:
    """Return the tool invocation id for events that document it, or ''."""
    value = payload.get("tool_use_id")
    return value if isinstance(value, str) else ""


def last_assistant_message(payload: dict) -> str:
    """Return the final assistant text for Stop or SubagentStop, or ''."""
    value = payload.get("last_assistant_message")
    return value if isinstance(value, str) else ""


def stop_hook_active(payload: dict) -> bool:
    """Return the Stop flag set when a prior Stop hook already blocked, or False."""
    value = payload.get("stop_hook_active")
    # because bool("false") is True, accept only a real bool so a wrong type stays False
    return value if isinstance(value, bool) else False


def agent_id(payload: dict) -> str:
    """Return the subagent id, or '' for non-subagent events."""
    value = payload.get("agent_id")
    return value if isinstance(value, str) else ""


def agent_type(payload: dict) -> str:
    """Return the subagent type, or '' for non-subagent events."""
    value = payload.get("agent_type")
    return value if isinstance(value, str) else ""


def agent_transcript_path(payload: dict) -> str:
    """Return the subagent transcript path, or ''."""
    value = payload.get("agent_transcript_path")
    # because agent_transcript_path is plan-named but undocumented, check it first and fall through to the documented transcript_path
    if not isinstance(value, str) or not value:
        value = payload.get("transcript_path")
    return value if isinstance(value, str) else ""


def prompt(payload: dict) -> str:
    """Return the UserPromptSubmit prompt text, or ''."""
    for key in _PROMPT_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def source(payload: dict) -> str:
    """Return the SessionStart source, or '' when absent."""
    value = payload.get("source")
    return value if isinstance(value, str) else ""


def file_path(payload: dict) -> str:
    """Return the path the tool targets resolved through the tool-input aliases."""
    tool_input = _tool_input(payload)
    for key in _FILE_PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def error(payload: dict) -> str:
    """Return the PostToolUseFailure error message, or ''."""
    value = payload.get("error")
    return value if isinstance(value, str) else ""


def is_interrupt(payload: dict) -> bool:
    """Return the failure-event interrupt flag, or False when absent."""
    value = payload.get("is_interrupt")
    # because bool("false") is True, accept only a real bool so a wrong type stays False
    return value if isinstance(value, bool) else False


def duration_ms(payload: dict) -> int:
    """Return the failure-event duration in milliseconds, or 0 when absent."""
    value = payload.get("duration_ms")
    # because bool is an int subclass, reject it before the numeric coercion
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def tool_calls(payload: dict) -> list[dict]:
    """Return the PostToolBatch tool_calls array, or [] when absent."""
    value = payload.get("tool_calls")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def task_id(payload: dict) -> str:
    """Return the task id for TaskCreated or TaskCompleted, or ''."""
    value = payload.get("task_id")
    return value if isinstance(value, str) else ""


def task_subject(payload: dict) -> str:
    """Return the TaskCompleted subject, or ''."""
    for key in _TASK_SUBJECT_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""
