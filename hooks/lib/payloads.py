from __future__ import annotations

import operator
import re
from pathlib import Path
from typing import TypedDict, cast

_TOOL_INPUT_KEYS = ("tool_input", "toolInput", "input")
_FILE_PATH_KEYS = ("file_path", "path")
_PROMPT_KEYS = ("prompt", "user_prompt")
_TASK_SUBJECT_KEYS = ("task_subject", "task_name")
_EDIT_TEXT_KEYS = ("patch", "command", "input")
_PATCH_FILE_RE = re.compile(r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s+(.+)$", re.MULTILINE)
_PATCH_MOVE_RE = re.compile(r"^\*\*\*\s+Move\s+to:\s+(.+)$", re.MULTILINE)


class FailurePayload(TypedDict):
    session_id: str
    cwd: str
    tool_name: str
    tool_use_id: str
    file_path: str
    error: str
    is_interrupt: bool
    duration_ms: int


class RecordPayload(TypedDict):
    session_id: str
    cwd: str
    tool_name: str
    tool_use_id: str
    file_path: str
    edit_text: str


def exact_string_dict(value: object) -> dict[str, object]:
    """Use built-in dict access because hook payloads cross a trust boundary, and overridden mapping methods can execute arbitrary code."""
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


def _exact_bool(fields: dict[str, object], key: str) -> bool:
    value = fields.get(key)
    return cast(bool, value) if operator.is_(type(value), bool) else False


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


def _exact_edit_text_value(value: object) -> str | None:
    if operator.is_(type(value), str):
        return cast(str, value)
    if not operator.is_(type(value), list):
        return None
    parts = cast(list[object], value)
    if not all(operator.is_(type(part), str) for part in parts):
        return None
    return "\n".join(cast(list[str], parts))


def _edit_text_from(tool_input: dict[str, object]) -> str:
    for key in _EDIT_TEXT_KEYS:
        text = _exact_edit_text_value(tool_input.get(key))
        if text is not None:
            return text
    return ""


def failure_payload(payload: object) -> FailurePayload:
    fields = exact_string_dict(payload)
    tool_input = _tool_input_from(fields)
    return {
        "session_id": _exact_string(fields, "session_id"),
        "cwd": _exact_string(fields, "cwd"),
        "tool_name": _exact_string(fields, "tool_name"),
        "tool_use_id": _exact_string(fields, "tool_use_id"),
        "file_path": _file_path_from(tool_input),
        "error": _exact_string(fields, "error"),
        "is_interrupt": _exact_bool(fields, "is_interrupt"),
        "duration_ms": _exact_int(fields, "duration_ms"),
    }


def record_payload(payload: object) -> RecordPayload:
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
    return _exact_string(exact_string_dict(payload), "session_id")


def turn_id(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "turn_id")


def cwd(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "cwd")


def tool_name(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "tool_name")


def tool_use_id(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "tool_use_id")


def agent_id(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "agent_id")


def agent_transcript_path(payload: object) -> str:
    fields = exact_string_dict(payload)
    value = _exact_string(fields, "agent_transcript_path")
    if not value:
        value = _exact_string(fields, "transcript_path")
    return value


def prompt(payload: object) -> str:
    fields = exact_string_dict(payload)
    for key in _PROMPT_KEYS:
        value = fields.get(key)
        if operator.is_(type(value), str):
            return cast(str, value)
    return ""


def source(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "source")


def file_path(payload: object) -> str:
    return _file_path_from(_tool_input(payload))


def error(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "error")


def is_interrupt(payload: object) -> bool:
    return _exact_bool(exact_string_dict(payload), "is_interrupt")


def stop_hook_active(payload: object) -> bool:
    return _exact_bool(exact_string_dict(payload), "stop_hook_active")


def duration_ms(payload: object) -> int:
    return _exact_int(exact_string_dict(payload), "duration_ms")


def tool_calls(payload: object) -> list[dict]:
    value = exact_string_dict(payload).get("tool_calls")
    if operator.is_(type(value), list):
        return [
            exact_string_dict(item)
            for item in cast(list[object], value)
            if operator.is_(type(item), dict)
        ]
    return []


def task_id(payload: object) -> str:
    return _exact_string(exact_string_dict(payload), "task_id")


def task_subject(payload: object) -> str:
    fields = exact_string_dict(payload)
    for key in _TASK_SUBJECT_KEYS:
        value = fields.get(key)
        if operator.is_(type(value), str):
            return cast(str, value)
    return ""


def patch_file_paths(text: str) -> tuple[str, ...]:
    """Shared because batch and record must recognize identical patch headers, or their ledger rows stop matching. Move destinations are included so a renamed file's landed content is still journalled and scanned under its new path."""
    headers = (match.strip().strip('"') for match in _PATCH_FILE_RE.findall(text))
    moves = (match.strip().strip('"') for match in _PATCH_MOVE_RE.findall(text))
    return (*headers, *moves)


def edited_paths(payload: object) -> tuple[str, ...]:
    """One implementation because batch and record used to diverge here, which silently broke the ledger dedup key."""
    fields = exact_string_dict(payload)
    tool_input = _tool_input_from(fields)
    path = _file_path_from(tool_input)
    if path:
        return (path,)
    text = _edit_text_from(tool_input)
    found = patch_file_paths(text)
    if _exact_string(fields, "tool_name").lower() == "bash":
        try:
            from . import pre_bash
        except ImportError:
            import pre_bash
        found = (*found, *pre_bash.write_paths(text))
    return found


def resolved_path(raw_path: str, cwd: Path) -> Path:
    """Expand a leading ~ here because batch used to skip it, so a tilde path keyed differently than the scan that read it. An unresolvable ~user is kept literal, since it cannot exist on disk and the read that follows already treats a missing path as unscannable."""
    try:
        path = Path(raw_path).expanduser()
    except (OSError, RuntimeError, ValueError):
        path = Path(raw_path)
    return path if path.is_absolute() else cwd / path
