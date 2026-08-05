"""Record tool failures and open session-scoped MCP backoff windows."""

from __future__ import annotations

import math
import posixpath
import re
import sys
import time
from typing import TypedDict, TypeGuard, cast

from lib import session_state
from lib.config import effective_config
from lib.hookio import read_payload, system_message, write_payload
from lib.payloads import FailurePayload, exact_string_dict, failure_payload
from lib.reporting import record_decision, run_with_ledger

FAILURE_EVENT = "PostToolUseFailure"
FAILURE_STREAKS_KEY = "failure_streaks"
MCP_HEALTH_KEY = "mcp_health"
GUIDANCE_THRESHOLD = 3
MCP_BASE_BACKOFF_SECONDS = 30
MCP_MAX_BACKOFF_SECONDS = 600
_MAX_TOOL_LENGTH = 263
_MAX_TARGET_LENGTH = 512
_MAX_MCP_SERVER_LENGTH = 128
_MAX_MCP_TOOL_LENGTH = 128
_MAX_SESSION_LENGTH = 128
_MAX_CWD_LENGTH = 4096
_MAX_ERROR_INPUT_LENGTH = 8192
_MAX_ERROR_LENGTH = 1024
_MAX_DURATION_MS = 86_400_000
_MAX_NOW = 100_000_000_000.0
_MAX_TIMESTAMP = _MAX_NOW + MCP_MAX_BACKOFF_SECONDS
_CONTROL_LIMIT = 32
_DELETE_CODE = 127
_BACKOFF_CAP_COUNT = 6
_MCP_PART_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
)
_SESSION_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,128}", re.ASCII)


class FailureEventData(TypedDict):
    tool: str
    target: str
    error: str
    interrupt: bool
    duration_ms: int
    now: float


class FailureCounts(TypedDict, total=False):
    tool_count: int
    target_count: int


class TrustedPayload(TypedDict):
    session_id: str
    cwd: str
    tool_name: str
    tool_use_id: str
    target: str
    error: str
    is_interrupt: bool
    duration_ms: int


class StreakData(TypedDict):
    count: int
    error: str
    is_interrupt: bool
    duration_ms: int


def _exact_string_dict(value: object) -> dict[str, object]:
    return exact_string_dict(value)


def _has_exact_type(value: object, expected: type) -> bool:
    return type(value) is expected


def _bounded_text(value: object, maximum: int) -> str:
    if not _has_exact_type(value, str):
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
    if not _has_exact_type(value, str):
        return ""
    clipped = cast(str, value)[:_MAX_ERROR_INPUT_LENGTH]
    printable = "".join(
        " "
        if ord(character) < _CONTROL_LIMIT or ord(character) == _DELETE_CODE
        else character
        for character in clipped
    )
    return " ".join(printable.split())[:_MAX_ERROR_LENGTH]


def _is_exact_number(value: object) -> TypeGuard[int | float]:
    return _has_exact_type(value, int) or _has_exact_type(value, float)


def _is_exact_int(value: object) -> TypeGuard[int]:
    return _has_exact_type(value, int)


def _canonical_duration(value: object) -> int:
    if not _is_exact_int(value):
        return 0
    if value < 0 or value > _MAX_DURATION_MS:
        return 0
    return value


def _valid_now(value: object) -> float | None:
    if not _is_exact_number(value):
        return None
    if not math.isfinite(value) or value < 0 or value > _MAX_NOW:
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
    """Return the trusted failure-hook payload projection."""
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


def _safe_config(config: object) -> dict[str, object]:
    source = _exact_string_dict(config)
    result: dict[str, object] = {}
    for key in ("state_root", "ledger_root"):
        value = _bounded_text(source.get(key), _MAX_CWD_LENGTH)
        if value:
            result[key] = value
    return result


def _config_roots(config: dict[str, object]) -> tuple[str | None, str | None]:
    state_root = _bounded_text(config.get("state_root"), _MAX_CWD_LENGTH) or None
    ledger_root = _bounded_text(config.get("ledger_root"), _MAX_CWD_LENGTH) or None
    return state_root, ledger_root


def parse_mcp_tool(tool_name: str) -> tuple[str, str] | None:
    """Return server and tool for one exact, bounded mcp__server__tool name."""
    if not _has_exact_type(tool_name, str) or not tool_name.startswith("mcp__"):
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


def failure_target(payload: dict) -> str:
    """Return one bounded scalar target without serializing arbitrary tool input."""
    return str(normalize_payload(payload)["target"])


def _next_streak(
    previous: object, error: str, *, interrupt: bool, duration_ms: int
) -> StreakData:
    count = 1
    prior = _exact_string_dict(previous)
    if prior:
        prior_count = prior.get("count")
        same_signature = (
            _has_exact_type(prior.get("error"), str)
            and prior.get("error") == error
            and prior.get("is_interrupt") is interrupt
        )
        if same_signature and _is_exact_int(prior_count) and prior_count > 0:
            count = prior_count + 1
    return {
        "count": count,
        "error": error,
        "is_interrupt": interrupt,
        "duration_ms": duration_ms,
    }


def _backoff_seconds(failure_count: int) -> int:
    if failure_count >= _BACKOFF_CAP_COUNT:
        return MCP_MAX_BACKOFF_SECONDS
    return MCP_BASE_BACKOFF_SECONDS * (1 << max(failure_count - 1, 0))


def _valid_nonnegative_int(value: object) -> int:
    if _is_exact_int(value) and value >= 0:
        return value
    return 0


def _valid_timestamp(value: object, default: float) -> float:
    if _is_exact_number(value):
        converted = float(value)
        if 0 <= converted <= _MAX_TIMESTAMP and math.isfinite(converted):
            return converted
    return default


def _update_streak(
    streaks: dict[str, object], key: str, event: FailureEventData
) -> int:
    next_streak = _next_streak(
        streaks.get(key),
        event["error"],
        interrupt=event["interrupt"],
        duration_ms=event["duration_ms"],
    )
    streaks[key] = next_streak
    return next_streak["count"]


def _updated_streaks(
    state: dict, event: FailureEventData, captured: FailureCounts
) -> dict:
    streaks = _exact_string_dict(state.get(FAILURE_STREAKS_KEY))
    tools = _exact_string_dict(streaks.get("tools"))
    targets = _exact_string_dict(streaks.get("targets"))
    tool = event["tool"]
    target = event["target"]
    if tool:
        captured["tool_count"] = _update_streak(tools, tool, event)
    if target:
        captured["target_count"] = _update_streak(targets, target, event)
    return {**streaks, "tools": tools, "targets": targets}


def _updated_mcp_health(state: dict, event: FailureEventData) -> dict | None:
    parsed = parse_mcp_tool(event["tool"])
    if parsed is None or event["interrupt"]:
        return None
    server, _ = parsed
    raw_health = state.get(MCP_HEALTH_KEY)
    health = _exact_string_dict(raw_health)
    raw_server = health.get(server)
    server_state = _exact_string_dict(raw_server)
    count = _valid_nonnegative_int(server_state.get("failure_count")) + 1
    previous_time = _valid_timestamp(server_state.get("last_failure_at"), event["now"])
    failure_time = max(event["now"], previous_time)
    retry_after = failure_time + _backoff_seconds(count)
    health[server] = {
        "failure_count": count,
        "last_failure_at": failure_time,
        "retry_after": retry_after,
        "error": event["error"],
        "is_interrupt": False,
        "duration_ms": event["duration_ms"],
    }
    return health


def _record_failure(
    state: dict, event: FailureEventData, captured: FailureCounts
) -> dict:
    trusted_state = _exact_string_dict(state)
    updated = dict(trusted_state)
    updated[FAILURE_STREAKS_KEY] = _updated_streaks(trusted_state, event, captured)
    health = _updated_mcp_health(trusted_state, event)
    if health is None:
        return updated
    return {**updated, MCP_HEALTH_KEY: health}


def _remove_key(mapping: object, key: str) -> tuple[object, bool]:
    if not key or not _has_exact_type(mapping, dict):
        return mapping, False
    copied = _exact_string_dict(mapping)
    if key not in copied:
        return mapping, False
    del copied[key]
    return copied, True


def _record_success(state: dict, payload: TrustedPayload) -> dict:
    if not _has_exact_type(state, dict):
        return state
    trusted_state = _exact_string_dict(state)
    updated = dict(trusted_state)
    streaks = trusted_state.get(FAILURE_STREAKS_KEY)
    if _has_exact_type(streaks, dict):
        streak_map = _exact_string_dict(streaks)
        tools, tool_removed = _remove_key(streak_map.get("tools"), payload["tool_name"])
        targets, target_removed = _remove_key(
            streak_map.get("targets"), payload["target"]
        )
        if tool_removed:
            streak_map["tools"] = tools
        if target_removed:
            streak_map["targets"] = targets
        if tool_removed or target_removed:
            updated[FAILURE_STREAKS_KEY] = streak_map

    parsed = parse_mcp_tool(payload["tool_name"])
    if parsed is None:
        return updated
    health, removed = _remove_key(trusted_state.get(MCP_HEALTH_KEY), parsed[0])
    if removed:
        updated[MCP_HEALTH_KEY] = health
    return updated


def record_success(payload: dict, config: dict | None = None) -> None:
    """Clear matching session failure state after one successful tool use."""
    try:
        trusted_payload = normalize_payload(payload)
        session_id = trusted_payload["session_id"]
        if not session_id:
            return
        trusted_config = _safe_config(config)
        cwd = str(trusted_payload["cwd"]) or None
        effective_config(trusted_config, cwd)
        state_root, _ = _config_roots(trusted_config)
        session_state.update_state(
            session_id,
            lambda state: _record_success(state, trusted_payload),
            state_root,
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(
            f"agent-discipline-watcher: success state update failed: {exc}\n"
        )


def _guidance(event: FailureEventData, captured: FailureCounts) -> str:
    if event["interrupt"] or not event["error"]:
        return ""
    tool_hit = captured.get("tool_count", 0) == GUIDANCE_THRESHOLD
    target_hit = captured.get("target_count", 0) == GUIDANCE_THRESHOLD
    if not tool_hit and not target_hit:
        return ""
    dimension = ""
    if tool_hit:
        dimension = f" for {event['tool']}"
    if target_hit:
        dimension += f" on {event['target']}"
    return (
        f"Tool failure repeated {GUIDANCE_THRESHOLD} times{dimension}: "
        f"{event['error']}. "
        "Stop retrying or weakening the change. Fix the root cause before calling the tool again."
    )


def _failure_event(payload: TrustedPayload, now: float) -> FailureEventData:
    return {
        "tool": payload["tool_name"],
        "target": payload["target"],
        "error": payload["error"],
        "interrupt": payload["is_interrupt"],
        "duration_ms": payload["duration_ms"],
        "now": now,
    }


def _capture_failure(
    session_id: str, event: FailureEventData, state_root: str | None
) -> FailureCounts | None:
    captured: FailureCounts = {}
    try:
        session_state.update_state(
            session_id,
            lambda state: _record_failure(state, event, captured),
            state_root,
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: failure state update failed: {exc}\n")
        return None
    return captured


def _record_guidance(
    session_id: str,
    payload: TrustedPayload,
    event: FailureEventData,
    ledger_root: str | None,
    turn_id: str,
) -> None:
    record_decision(
        session_id=session_id,
        hook="failure",
        event=FAILURE_EVENT,
        family="tool_failure",
        rule="repeated_failure",
        path=event["target"],
        tool_use_id=payload["tool_use_id"],
        outcome="inject",
        duration_ms=event["duration_ms"],
        turn_id=turn_id,
        root=ledger_root,
    )


def _failure_gate(
    payload: TrustedPayload,
    state_root: str | None,
    ledger_root: str | None,
    current_time: float | None,
    turn_id: str,
) -> dict:
    session_id = payload["session_id"]
    if not session_id or current_time is None or not payload["error"]:
        return {}
    event = _failure_event(payload, current_time)
    captured = _capture_failure(session_id, event, state_root)
    if captured is None:
        return {}
    message = _guidance(event, captured)
    if not message:
        return {}
    _record_guidance(session_id, payload, event, ledger_root, turn_id)
    return system_message(message)


def _run_failure(
    payload: TrustedPayload,
    state_root: str | None,
    ledger_root: str | None,
    current_time: float | None,
) -> dict:
    return run_with_ledger(
        hook="failure",
        payload=dict(payload),
        gate=lambda turn_id: _failure_gate(
            payload, state_root, ledger_root, current_time, turn_id
        ),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def run(payload: dict, config: dict | None = None, now: float | None = None) -> dict:
    """Persist one failure and inject guidance at the exact repeat threshold."""
    try:
        trusted_payload = normalize_payload(payload)
        if not trusted_payload["session_id"]:
            return {}
        trusted_config = _safe_config(config)
        cwd = str(trusted_payload["cwd"]) or None
        effective_config(trusted_config, cwd)
        state_root, ledger_root = _config_roots(trusted_config)
        clock = time.time() if now is None else now
        return _run_failure(
            trusted_payload,
            state_root,
            ledger_root,
            _valid_now(clock),
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: failure hook failed: {exc}\n")
        return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
