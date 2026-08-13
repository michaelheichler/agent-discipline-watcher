"""Block MCP calls while their session-scoped server backoff is active."""

from __future__ import annotations

import math
import sys
import time

from failure import (
    _MAX_TIMESTAMP,
    MCP_HEALTH_KEY,
    TrustedPayload,
    _config_roots,
    _exact_string_dict,
    _is_exact_int,
    _is_exact_number,
    _safe_config,
    _valid_now,
    normalize_payload,
    parse_mcp_tool,
)
from lib import session_state
from lib.config import effective_config
from lib.hookio import PARSE_FAILURE, allow, claude_pretool_response, deny, read_payload, write_payload
from lib.reporting import record_decision, run_with_ledger

PRE_TOOL_EVENT = "PreToolUse"
UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this MCP call and blocked it rather than letting it through. "
    "Repair the gate config and retry. Cause: "
)


def _active_backoff(state: dict, server: str, now: float) -> tuple[int, float] | None:
    trusted_state = _exact_string_dict(state)
    health = _exact_string_dict(trusted_state.get(MCP_HEALTH_KEY))
    if not health:
        return None
    entry = _exact_string_dict(health.get(server))
    if not entry:
        return None
    count = entry.get("failure_count")
    retry_after = entry.get("retry_after")
    if not _is_exact_int(count) or count <= 0:
        return None
    if not _is_exact_number(retry_after):
        return None
    deadline = float(retry_after)
    if not math.isfinite(deadline) or deadline > _MAX_TIMESTAMP or now >= deadline:
        return None
    return count, deadline


def _read_mcp_state(session_id: str, state_root: str | None) -> dict | None:
    try:
        return session_state.read_state(session_id, state_root)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: MCP health read failed: {exc}\n")
        return None


def _record_backoff(
    payload: TrustedPayload, server: str, ledger_root: str | None, turn_id: str,
) -> None:
    record_decision(
        session_id=payload["session_id"],
        hook="pre_mcp",
        event=PRE_TOOL_EVENT,
        family="mcp_health",
        rule="server_backoff",
        path=server,
        tool_use_id=payload["tool_use_id"],
        outcome="block",
        duration_ms=0,
        turn_id=turn_id,
        root=ledger_root,
    )


def _pre_mcp_gate(
    payload: TrustedPayload,
    state_root: str | None,
    ledger_root: str | None,
    current_time: float | None,
    turn_id: str,
) -> dict:
    session_id = payload["session_id"]
    parsed = parse_mcp_tool(payload["tool_name"])
    if not session_id or parsed is None or current_time is None:
        return allow()
    server, _ = parsed
    state = _read_mcp_state(session_id, state_root)
    if state is None:
        return allow()
    active = _active_backoff(state, server, current_time)
    if active is None:
        return allow()
    count, deadline = active
    noun = "failure" if count == 1 else "failures"
    reason = (
        f"MCP server {server} is unavailable after {count} {noun} until {deadline:.3f}. "
        "Fix the provider root cause or retry after expiry."
    )
    _record_backoff(payload, server, ledger_root, turn_id)
    return deny(reason)


def _run_pre_mcp(
    payload: TrustedPayload,
    state_root: str | None,
    ledger_root: str | None,
    current_time: float | None,
) -> dict:
    return run_with_ledger(
        hook="pre_mcp",
        payload=dict(payload),
        gate=lambda turn_id: _pre_mcp_gate(
            payload, state_root, ledger_root, current_time, turn_id,
        ),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def run(payload: dict, config: dict | None = None, now: float | None = None) -> dict:
    """Deny a known-unhealthy MCP server until expiry, otherwise fail safe."""
    if payload is PARSE_FAILURE:
        return deny(UNDECIDABLE + "unreadable hook payload")
    try:
        trusted_payload = normalize_payload(payload)
        if not trusted_payload["session_id"]:
            return allow()
        trusted_config = _safe_config(config)
        cwd = str(trusted_payload["cwd"]) or None
        effective_config(trusted_config, cwd)
        state_root, ledger_root = _config_roots(trusted_config)
        clock = time.time() if now is None else now
        return _run_pre_mcp(
            trusted_payload,
            state_root,
            ledger_root,
            _valid_now(clock),
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: pre-MCP hook failed: {exc}\n")
        return allow()


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
