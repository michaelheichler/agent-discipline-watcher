from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from typing import TypedDict

from lib import session_state
from lib.config import StorageRoots
from lib.hookio import read_payload, system_message, write_payload
from lib.mcp_health import (
    MAX_TIMESTAMP,
    MCP_HEALTH_KEY,
    MCP_MAX_BACKOFF_SECONDS,
    McpHealthEntry,
    TrustedPayload,
    has_exact_type,
    is_exact_int,
    is_exact_number,
    normalize_payload,
    parse_mcp_tool,
    safe_config,
    valid_now,
)
from lib.mcp_health import config_roots as _config_roots
from lib.payloads import exact_string_dict
from lib.reporting import record_decision, run_with_ledger

FAILURE_EVENT = "PostToolUseFailure"
FAILURE_STREAKS_KEY = "failure_streaks"
GUIDANCE_THRESHOLD = 3
MCP_BASE_BACKOFF_SECONDS = 30
_BACKOFF_CAP_COUNT = 6


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


class StreakData(TypedDict):
    count: int
    error: str
    is_interrupt: bool
    duration_ms: int


@dataclass(frozen=True, slots=True)
class _FailureSignature:
    error: str
    interrupt: bool
    duration_ms: int


@dataclass(frozen=True, slots=True)
class FailureRunContext:
    payload: TrustedPayload
    roots: StorageRoots
    current_time: float | None


def _next_streak(previous: object, signature: _FailureSignature) -> StreakData:
    count = 1
    prior = exact_string_dict(previous)
    if prior:
        prior_count = prior.get("count")
        same_signature = (
            has_exact_type(prior.get("error"), str)
            and prior.get("error") == signature.error
            and prior.get("is_interrupt") is signature.interrupt
        )
        if same_signature and is_exact_int(prior_count) and prior_count > 0:
            count = prior_count + 1
    return {
        "count": count,
        "error": signature.error,
        "is_interrupt": signature.interrupt,
        "duration_ms": signature.duration_ms,
    }


def _backoff_seconds(failure_count: int) -> int:
    if failure_count >= _BACKOFF_CAP_COUNT:
        return MCP_MAX_BACKOFF_SECONDS
    return MCP_BASE_BACKOFF_SECONDS * (1 << max(failure_count - 1, 0))


def _valid_nonnegative_int(value: object) -> int:
    if is_exact_int(value) and value >= 0:
        return value
    return 0


def _valid_timestamp(value: object, default: float) -> float:
    if is_exact_number(value):
        converted = float(value)
        if 0 <= converted <= MAX_TIMESTAMP and math.isfinite(converted):
            return converted
    return default


def _update_streak(
    streaks: dict[str, object], key: str, event: FailureEventData
) -> int:
    signature = _FailureSignature(
        event["error"], event["interrupt"], event["duration_ms"]
    )
    next_streak = _next_streak(streaks.get(key), signature)
    streaks[key] = next_streak
    return next_streak["count"]


def _updated_streaks(
    state: dict, event: FailureEventData, captured: FailureCounts
) -> dict:
    streaks = exact_string_dict(state.get(FAILURE_STREAKS_KEY))
    tools = exact_string_dict(streaks.get("tools"))
    targets = exact_string_dict(streaks.get("targets"))
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
    health = exact_string_dict(raw_health)
    raw_server = health.get(server)
    server_state = exact_string_dict(raw_server)
    count = _valid_nonnegative_int(server_state.get("failure_count")) + 1
    previous_time = _valid_timestamp(server_state.get("last_failure_at"), event["now"])
    failure_time = max(event["now"], previous_time)
    retry_after = failure_time + _backoff_seconds(count)
    entry: McpHealthEntry = {
        "failure_count": count,
        "last_failure_at": failure_time,
        "retry_after": retry_after,
        "error": event["error"],
        "is_interrupt": False,
        "duration_ms": event["duration_ms"],
    }
    health[server] = entry
    return health


def _record_failure(
    state: dict, event: FailureEventData, captured: FailureCounts
) -> dict:
    trusted_state = exact_string_dict(state)
    updated = dict(trusted_state)
    updated[FAILURE_STREAKS_KEY] = _updated_streaks(trusted_state, event, captured)
    health = _updated_mcp_health(trusted_state, event)
    if health is None:
        return updated
    return {**updated, MCP_HEALTH_KEY: health}


def _remove_key(mapping: object, key: str) -> tuple[object, bool]:
    if not key or not has_exact_type(mapping, dict):
        return mapping, False
    copied = exact_string_dict(mapping)
    if key not in copied:
        return mapping, False
    del copied[key]
    return copied, True


def _record_success(state: dict, payload: TrustedPayload) -> dict:
    if not has_exact_type(state, dict):
        return state
    trusted_state = exact_string_dict(state)
    updated = dict(trusted_state)
    streaks = trusted_state.get(FAILURE_STREAKS_KEY)
    if has_exact_type(streaks, dict):
        streak_map = exact_string_dict(streaks)
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
    """Discard matching failure state because a successful use proves the recorded streak and backoff are stale."""
    try:
        trusted_payload = normalize_payload(payload)
        session_id = trusted_payload["session_id"]
        if not session_id:
            return
        trusted_config = safe_config(config)
        roots = _config_roots(trusted_config)
        session_state.update_state_strict(
            session_id,
            lambda state: _record_success(state, trusted_payload),
            roots.state,
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
        session_state.update_state_strict(
            session_id,
            lambda state: _record_failure(state, event, captured),
            state_root,
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: failure state update failed: {exc}\n")
        return None
    return captured


def _record_guidance(
    context: FailureRunContext, event: FailureEventData, turn_id: str
) -> None:
    record_decision(
        session_id=context.payload["session_id"],
        hook="failure",
        event=FAILURE_EVENT,
        family="tool_failure",
        rule="repeated_failure",
        path=event["target"],
        tool_use_id=context.payload["tool_use_id"],
        outcome="inject",
        duration_ms=event["duration_ms"],
        turn_id=turn_id,
        root=context.roots.ledger,
    )


def _failure_gate(context: FailureRunContext, turn_id: str) -> dict:
    session_id = context.payload["session_id"]
    if (
        not session_id
        or context.current_time is None
        or not context.payload["error"]
    ):
        return {}
    event = _failure_event(context.payload, context.current_time)
    captured = _capture_failure(session_id, event, context.roots.state)
    if captured is None:
        return {}
    message = _guidance(event, captured)
    if not message:
        return {}
    _record_guidance(context, event, turn_id)
    return system_message(message)


def _run_failure(context: FailureRunContext) -> dict:
    return run_with_ledger(
        hook="failure",
        payload=dict(context.payload),
        gate=lambda turn_id: _failure_gate(context, turn_id),
        ledger_root=context.roots.ledger,
        state_root=context.roots.state,
    )


def run(payload: dict, config: dict | None = None, now: float | None = None) -> dict:
    """Delay guidance until the repeat threshold because transient failures need no intervention and earlier messages would add noise."""
    try:
        trusted_payload = normalize_payload(payload)
        if not trusted_payload["session_id"]:
            return {}
        trusted_config = safe_config(config)
        roots = _config_roots(trusted_config)
        clock = time.time() if now is None else now
        context = FailureRunContext(trusted_payload, roots, valid_now(clock))
        return _run_failure(context)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: failure hook failed: {exc}\n")
        return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
