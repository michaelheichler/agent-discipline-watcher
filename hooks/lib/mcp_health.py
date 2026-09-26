"""Kept in lib because two hooks must agree on input bounds."""

from __future__ import annotations

import math
import operator
import posixpath
import re
from typing import TypedDict, TypeGuard, cast

from .config import StorageRoots
from .payloads import FailurePayload, exact_string_dict, failure_payload

MCP_HEALTH_KEY = "mcp_health"
MCP_MAX_BACKOFF_SECONDS = 600
MAX_NOW = 100_000_000_000.0
MAX_TIMESTAMP = MAX_NOW + MCP_MAX_BACKOFF_SECONDS
_MAX_TOOL_LENGTH = 263
_MAX_TARGET_LENGTH = 512
_MAX_MCP_SERVER_LENGTH = 128
_MAX_MCP_TOOL_LENGTH = 128
_MAX_SESSION_LENGTH = 128
_MAX_CWD_LENGTH = 4096
_MAX_ERROR_INPUT_LENGTH = 8192
_MAX_ERROR_LENGTH = 1024
_MAX_DURATION_MS = 86_400_000
_CONTROL_LIMIT = 32
_DELETE_CODE = 127
_MCP_PART_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
)
_SESSION_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,128}", re.ASCII)


class TrustedPayload(TypedDict):
    session_id: str
    cwd: str
    tool_name: str
    tool_use_id: str
    target: str
    error: str
    is_interrupt: bool
    duration_ms: int


class McpHealthEntry(TypedDict):
    failure_count: int
    last_failure_at: float
    retry_after: float
    error: str
    is_interrupt: bool
    duration_ms: int


def has_exact_type(value: object, expected: type) -> bool:
    return operator.is_(type(value), expected)


def is_exact_number(value: object) -> TypeGuard[int | float]:
    return has_exact_type(value, int) or has_exact_type(value, float)


def is_exact_int(value: object) -> TypeGuard[int]:
    return has_exact_type(value, int)


def _bounded_text(value: object, maximum: int) -> str:
    if not has_exact_type(value, str):
        return ""
    text = cast(str, value)
    if not text or len(text) > maximum:
        return ""
    if any(
        ord(character) < _CONTROL_LIMIT or ord(character) == _DELETE_CODE
        for character in text
    ):
        return ""
    return text


def _normalized_error(value: object) -> str:
    if not has_exact_type(value, str):
        return ""
    clipped = cast(str, value)[:_MAX_ERROR_INPUT_LENGTH]
    printable = "".join(
        " "
        if ord(character) < _CONTROL_LIMIT or ord(character) == _DELETE_CODE
        else character
        for character in clipped
    )
    return " ".join(printable.split())[:_MAX_ERROR_LENGTH]


def _canonical_duration(value: object) -> int:
    if not is_exact_int(value):
        return 0
    if value < 0 or value > _MAX_DURATION_MS:
        return 0
    return value


def valid_now(value: object) -> float | None:
    if not is_exact_number(value):
        return None
    if not math.isfinite(value) or value < 0 or value > MAX_NOW:
        return None
    return float(value)


def _target(raw_target: str, cwd: str) -> str:
    target = _bounded_text(raw_target, _MAX_TARGET_LENGTH)
    if not target:
        return ""
    if posixpath.isabs(target):
        canonical = posixpath.abspath(posixpath.normpath(target))
    elif cwd and posixpath.isabs(cwd):
        canonical = posixpath.abspath(posixpath.normpath(posixpath.join(cwd, target)))
    else:
        canonical = posixpath.normpath(target)
    return canonical if len(canonical) <= _MAX_TARGET_LENGTH else ""


def normalize_payload(payload: object) -> TrustedPayload:
    """Bound payload-derived keys and paths because hook input crosses a trust boundary."""
    projected: FailurePayload = failure_payload(payload)
    session_id = _bounded_text(projected["session_id"], _MAX_SESSION_LENGTH)
    if session_id in (".", "..") or not _SESSION_PATTERN.fullmatch(session_id):
        session_id = ""
    cwd = _bounded_text(projected["cwd"], _MAX_CWD_LENGTH)
    return {
        "session_id": session_id,
        "cwd": cwd,
        "tool_name": _bounded_text(projected["tool_name"], _MAX_TOOL_LENGTH),
        "tool_use_id": _bounded_text(projected["tool_use_id"], _MAX_TOOL_LENGTH),
        "target": _target(projected["file_path"], cwd),
        "error": _normalized_error(projected["error"]),
        "is_interrupt": projected["is_interrupt"],
        "duration_ms": _canonical_duration(projected["duration_ms"]),
    }


def safe_config(config: object) -> dict[str, object]:
    source = exact_string_dict(config)
    result: dict[str, object] = {}
    for key in ("state_root", "ledger_root"):
        value = _bounded_text(source.get(key), _MAX_CWD_LENGTH)
        if value:
            result[key] = value
    return result


def config_roots(config: dict[str, object]) -> StorageRoots:
    state_root = _bounded_text(config.get("state_root"), _MAX_CWD_LENGTH) or None
    ledger_root = _bounded_text(config.get("ledger_root"), _MAX_CWD_LENGTH) or None
    return StorageRoots(state_root, ledger_root)


def parse_mcp_tool(tool_name: str) -> tuple[str, str] | None:
    """Reject malformed and oversized MCP names because they become persistent health-map keys."""
    if not has_exact_type(tool_name, str) or not tool_name.startswith("mcp__"):
        return None
    server, separator, tool = tool_name[5:].partition("__")
    if not separator:
        return None
    if not _is_valid_mcp_part(server, _MAX_MCP_SERVER_LENGTH):
        return None
    if not _is_valid_mcp_part(tool, _MAX_MCP_TOOL_LENGTH):
        return None
    return server, tool


def _is_valid_mcp_part(value: str, maximum: int) -> bool:
    if not value or len(value) > maximum:
        return False
    return all(character in _MCP_PART_CHARACTERS for character in value)
