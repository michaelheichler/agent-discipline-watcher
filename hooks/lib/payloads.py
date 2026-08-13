"""Typed projections over untrusted hook event payloads."""

from __future__ import annotations

import operator
from typing import TypedDict, cast

_TOOL_INPUT_KEYS = ("tool_input", "toolInput", "input")
_FILE_PATH_KEYS = ("file_path", "path")
_PROMPT_KEYS = ("prompt", "user_prompt")
_TASK_SUBJECT_KEYS = ("task_subject", "task_name")
_EDIT_TEXT_KEYS = ("patch", "command", "input")


class FailurePayload(TypedDict):
    """Exact-type scalar projection used by failure and MCP hooks."""

    session_id: str
    cwd: str
    tool_name: str
    tool_use_id: str
    file_path: str
    error: str
    is_interrupt: bool
    duration_ms: int


class RecordPayload(TypedDict):
    """Exact-type projection used by the edit journal and scanner hook."""

    session_id: str
    cwd: str
    tool_name: str
    tool_use_id: str
    file_path: str
    edit_text: str


def exact_string_dict(value: object) -> dict[str, object]:
    """Copy exact-string members without invoking untrusted mapping methods."""
    if not operator.is_(type(value), dict):
        return {}
    result: dict[str, object] = {}
    for key, item in dict.items(cast(dict[object, object], value)):
        if operator.is_(type(key), str):
            result[cast(str, key)] = item
    return result


def _exact_string(fields: dict[str, object], key: str) -> str:
    value = fields.get(key)
    return cast(str, value) if operator.is_(type(value), str) else ""


def _is_exact_bool_field(fields: dict[str, object], key: str) -> bool:
    value = fields.get(key)
    return cast(bool, value) if operator.is_(type(value), bool) else False


_read_exact_bool = _is_exact_bool_field


def _exact_int(fields: dict[str, object], key: str) -> int:
    value = fields.get(key)
    return cast(int, value) if operator.is_(type(value), int) else 0


def _tool_input_from(fields: dict[str, object]) -> dict[str, object]:
    for key in _TOOL_INPUT_KEYS:
        value = exact_string_dict(fields.get(key))
        if value:
            return value
    return {}


def _file_path_from(tool_input: dict[str, object]) -> str:
    for key in _FILE_PATH_KEYS:
        value = _exact_string(tool_input, key)
        if value:
            return value
    return ""


def _edit_text_from(tool_input: dict[str, object]) -> str:
    for key in _EDIT_TEXT_KEYS:
        value = tool_input.get(key)
        if operator.is_(type(value), str):
            return cast(str, value)
        if operator.is_(type(value), list):
            parts = cast(list[object], value)
            if all(operator.is_(type(part), str) for part in parts):
                return "\n".join(cast(list[str], parts))
    return ""


def failure_payload(payload: object) -> FailurePayload:
    """Return exact built-in failure/MCP event fields, or neutral defaults."""
    fields = exact_string_dict(payload)
    tool_input = _tool_input_from(fields)
    return {
        "session_id": _exact_string(fields, "session_id"),
        "cwd": _exact_string(fields, "cwd"),
        "tool_name": _exact_string(fields, "tool_name"),
        "tool_use_id": _exact_string(fields, "tool_use_id"),
        "file_path": _file_path_from(tool_input),
        "error": _exact_string(fields, "error"),
        "is_interrupt": _read_exact_bool(fields, "is_interrupt"),
        "duration_ms": _exact_int(fields, "duration_ms"),
    }


def record_payload(payload: object) -> RecordPayload:
    """Return exact built-in PostToolUse fields, or neutral defaults."""
    fields = exact_string_dict(payload)
    tool_input = _tool_input_from(fields)
    return {
        "session_id": _exact_string(fields, "session_id"),
        "cwd": _exact_string(fields, "cwd"),
        "tool_name": _exact_string(fields, "tool_name"),
        "tool_use_id": _exact_string(fields, "tool_use_id"),
        "file_path": _file_path_from(tool_input),
        "edit_text": _edit_text_from(tool_input),
    }


def _tool_input(payload: object) -> dict[str, object]:
    return _tool_input_from(exact_string_dict(payload))


def session_id(payload: object) -> str:
    """Return the session id, or '' when absent."""
    return _exact_string(exact_string_dict(payload), "session_id")


def cwd(payload: object) -> str:
    """Return the working directory the hook ran in, or '' when absent."""
    return _exact_string(exact_string_dict(payload), "cwd")


def tool_name(payload: object) -> str:
    """Return the tool name for a Pre/PostToolUse or failure event, or ''."""
    return _exact_string(exact_string_dict(payload), "tool_name")


def tool_use_id(payload: object) -> str:
    """Return the tool invocation id for events that document it, or ''."""
    return _exact_string(exact_string_dict(payload), "tool_use_id")


def agent_transcript_path(payload: object) -> str:
    """Return the subagent transcript path, or ''."""
    fields = exact_string_dict(payload)
    value = _exact_string(fields, "agent_transcript_path")
    if not value:
        value = _exact_string(fields, "transcript_path")
    return value


def prompt(payload: object) -> str:
    """Return the UserPromptSubmit prompt text, or ''."""
    fields = exact_string_dict(payload)
    for key in _PROMPT_KEYS:
        value = fields.get(key)
        if operator.is_(type(value), str):
            return cast(str, value)
    return ""


def source(payload: object) -> str:
    """Return the SessionStart source, or '' when absent."""
    return _exact_string(exact_string_dict(payload), "source")


def file_path(payload: object) -> str:
    """Return the path the tool targets resolved through the tool-input aliases."""
    return _file_path_from(_tool_input(payload))


def error(payload: object) -> str:
    """Return the PostToolUseFailure error message, or ''."""
    return _exact_string(exact_string_dict(payload), "error")


def is_interrupt(payload: object) -> bool:
    """Return the failure-event interrupt flag, or False when absent."""
    return _read_exact_bool(exact_string_dict(payload), "is_interrupt")


def stop_hook_active(payload: object) -> bool:
    return _read_exact_bool(exact_string_dict(payload), "stop_hook_active")


def duration_ms(payload: object) -> int:
    """Return the failure-event duration in milliseconds, or 0 when absent."""
    return _exact_int(exact_string_dict(payload), "duration_ms")


def tool_calls(payload: object) -> list[dict]:
    """Return the PostToolBatch tool_calls array, or [] when absent."""
    value = exact_string_dict(payload).get("tool_calls")
    if operator.is_(type(value), list):
        return [
            exact_string_dict(item)
            for item in cast(list[object], value)
            if operator.is_(type(item), dict)
        ]
    return []


def task_id(payload: object) -> str:
    """Return the task id for TaskCreated or TaskCompleted, or ''."""
    return _exact_string(exact_string_dict(payload), "task_id")


def task_subject(payload: object) -> str:
    """Return the TaskCompleted subject, or ''."""
    fields = exact_string_dict(payload)
    for key in _TASK_SUBJECT_KEYS:
        value = fields.get(key)
        if operator.is_(type(value), str):
            return cast(str, value)
    return ""
