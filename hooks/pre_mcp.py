"""Blocked here because any MCP server with a filesystem-write tool could otherwise edit the watcher's own config, state, or install without passing through any other gate."""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from failure import (
    _MAX_TIMESTAMP,
    MCP_HEALTH_KEY,
    TrustedPayload,
    _config_roots,
    _is_exact_int,
    _is_exact_number,
    _safe_config,
    _valid_now,
    normalize_payload,
    parse_mcp_tool,
)
from lib import session_state
from lib.config import StorageRoots, effective_config
from lib.hookio import PARSE_FAILURE, allow, claude_pretool_response, deny, read_payload, write_payload
from lib.mcp_paths import mcp_target_paths, mcp_write_contents
from lib.payloads import exact_string_dict
from lib.protected import path_findings
from lib.reporting import record_decision, record_findings, run_with_ledger, verdict_message

PRE_TOOL_EVENT = "PreToolUse"
UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this MCP call and blocked it rather than letting it through. "
    "Repair the gate config and retry. Cause: "
)


@dataclass(frozen=True, slots=True)
class McpRunContext:
    raw_payload: object
    payload: TrustedPayload
    config: dict
    roots: StorageRoots
    current_time: float | None


def _active_backoff(state: dict, server: str, now: float) -> tuple[int, float] | None:
    trusted_state = exact_string_dict(state)
    health = exact_string_dict(trusted_state.get(MCP_HEALTH_KEY))
    if not health:
        return None
    entry = exact_string_dict(health.get(server))
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
    context: McpRunContext, server: str, turn_id: str
) -> None:
    record_decision(
        session_id=context.payload["session_id"],
        hook="pre_mcp",
        event=PRE_TOOL_EVENT,
        family="mcp_health",
        rule="server_backoff",
        path=server,
        tool_use_id=context.payload["tool_use_id"],
        outcome="block",
        duration_ms=0,
        turn_id=turn_id,
        root=context.roots.ledger,
    )


def _mcp_tool_input(raw_payload: object) -> dict[str, object]:
    fields = exact_string_dict(raw_payload)
    for key in ("tool_input", "toolInput", "input"):
        value = exact_string_dict(fields.get(key))
        if value:
            return value
    return {}


def _resolved_path(path: str, cwd: str) -> str:
    """Left tilde-prefixed here for path_findings to expand, since Path.expanduser() raises on an unresolvable ~user and path_findings already has a dedicated fallback finding for that case."""
    if path.startswith("~"):
        return path
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    base = Path(cwd) if cwd else Path(os.getcwd())
    return str(base / candidate)


def _candidate_path_findings(tool_input: dict[str, object], cwd: str) -> list[dict]:
    candidates = mcp_write_contents(tool_input) or [None]
    findings: list[dict] = []
    for path in mcp_target_paths(tool_input):
        resolved = _resolved_path(path, cwd)
        for content in candidates:
            findings.extend(path_findings(resolved, content=content))
    return findings


def _protected_findings(raw_payload: object, cwd: str) -> list[dict]:
    """Scanned once per candidate body because grants_escape must judge each field alone, and rows dedupe because the path-based findings repeat per candidate."""
    rows = _candidate_path_findings(_mcp_tool_input(raw_payload), cwd)
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["rule"], row["detail"])
        if key in seen:
            continue
        seen.add(key)
        findings.append(row)
    return findings


def _protected_verdict(raw_payload: object, cwd: str) -> dict:
    """Denied without a ledger row because this path runs exactly when session identity or config state is unusable, and observability must not gate protection."""
    findings = _protected_findings(raw_payload, cwd)
    if not findings:
        return allow()
    summary = " ".join(f"{item['detail']}. {item['action']}" for item in findings[:3])
    return deny(summary)


def _fail_safe(raw_payload: object) -> dict:
    """Backoff may degrade to allow, the protected scan may not, so an errored run still re-checks the write target before letting the call through."""
    try:
        fields = exact_string_dict(raw_payload)
        raw_cwd = fields.get("cwd")
        return _protected_verdict(raw_payload, raw_cwd if isinstance(raw_cwd, str) else "")
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        return deny(UNDECIDABLE + str(exc))


def _protected_response(context: McpRunContext, turn_id: str) -> dict:
    started = time.monotonic()
    findings = _protected_findings(context.raw_payload, context.payload["cwd"])
    if not findings:
        return {}
    decisions = record_findings(
        session_id=context.payload["session_id"], hook="pre_mcp",
        event=PRE_TOOL_EVENT, findings=findings, turn_id=turn_id,
        tool_use_id=context.payload["tool_use_id"],
        duration_ms=int((time.monotonic() - started) * 1000),
        root=context.roots.ledger, config=context.config,
    )
    kind, message = verdict_message(decisions, context.config)
    return deny(message) if kind == "block" else {}


def _backoff_response(context: McpRunContext, turn_id: str) -> dict:
    payload = context.payload
    current_time = context.current_time
    session_id = payload["session_id"]
    parsed = parse_mcp_tool(payload["tool_name"])
    if not session_id or parsed is None or current_time is None:
        return allow()
    server, _ = parsed
    state = _read_mcp_state(session_id, context.roots.state)
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
    _record_backoff(context, server, turn_id)
    return deny(reason)


def _pre_mcp_gate(context: McpRunContext, turn_id: str) -> dict:
    protected = _protected_response(context, turn_id)
    if protected:
        return protected
    return _backoff_response(context, turn_id)


def _run_pre_mcp(context: McpRunContext) -> dict:
    return run_with_ledger(
        hook="pre_mcp",
        payload=dict(context.payload),
        gate=lambda turn_id: _pre_mcp_gate(context, turn_id),
        ledger_root=context.roots.ledger,
        state_root=context.roots.state,
    )


def run(payload: dict, config: dict | None = None, now: float | None = None) -> dict:
    """Deny an MCP call that targets a protected path, or a known-unhealthy server until expiry, otherwise fail safe."""
    if payload is PARSE_FAILURE:
        return deny(UNDECIDABLE + "unreadable hook payload")
    try:
        trusted_payload = normalize_payload(payload)
        if not trusted_payload["session_id"]:
            return _protected_verdict(payload, trusted_payload["cwd"])
        trusted_config = _safe_config(config)
        cwd = str(trusted_payload["cwd"]) or None
        effective_config(trusted_config, cwd)
        roots = _config_roots(trusted_config)
        clock = time.time() if now is None else now
        context = McpRunContext(
            raw_payload=payload,
            payload=trusted_payload,
            config=trusted_config,
            roots=roots,
            current_time=_valid_now(clock),
        )
        return _run_pre_mcp(context)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: pre-MCP hook failed: {exc}\n")
        return _fail_safe(payload)


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
