"""Scan a subagent's final message without ending the parent turn."""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

from lib import payloads, reporting, session_state
from lib.config import effective_config, resolve_outcome
from lib.done_claims import scan_done_claims
from lib.hookio import read_payload, stop_block, write_payload
from lib.reporting import compact_block, run_with_ledger
from lib.scanner import scan_all, scannable_text

MESSAGE_PATH = "last_assistant_message.md"
SUBAGENT_STOP_EVENT = "SubagentStop"
PENDING_BLOCK_KEY = "pending_subagent_stop_block"
UNKEYED_AGENT_KEY = "missing:"


def run(payload: dict, config: dict | None = None) -> dict:
    cfg = effective_config(config, payloads.cwd(payload) or None)
    session_id = payloads.session_id(payload)
    # Because SubagentStop defines stop_hook_active as retry, ownership stays per agent.
    retry = payloads.stop_hook_active(payload)
    agent = {
        "agent_id": payloads.agent_id(payload),
        "agent_type": payloads.agent_type(payload),
    }
    agent_key = _pending_agent_key(agent["agent_id"])
    # No turn advance because the D7 denominator counts user turns, not delegations.
    base_row = {
        "session_id": session_id,
        "hook": "subagent_stop",
        "event": SUBAGENT_STOP_EVENT,
        "tool_use_id": "",
        "agent_id": agent["agent_id"],
        "agent_type": agent["agent_type"],
    }

    def record(row: dict) -> None:
        # Built here because reporting.record_decision has no agent fields.
        if row["outcome"] not in reporting.OUTCOMES:
            raise ValueError(f"unknown outcome: {row['outcome']!r}")
        reporting.append_row(
            {"ts": reporting.now_iso(), **base_row, **row},
            cfg.get("ledger_root"),
        )

    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        findings = _scan_message(payloads.last_assistant_message(payload), cfg)
        decisions = [(finding, resolve_outcome(finding, cfg)) for finding in findings]
        duration_ms = int((time.monotonic() - started) * 1000)
        if session_id:
            _record_decisions(record, turn_id, decisions, duration_ms)
        blocking = [finding for finding, outcome in decisions if outcome == "block"]
        if blocking:
            if session_id:
                _mark_pending_block(session_id, agent_key, cfg.get("state_root"))
            reason, _ = compact_block(blocking, cfg)
            return stop_block(reason)
        if (
            retry
            and session_id
            and _consume_pending_block(
                session_id, agent_key, cfg.get("state_root")
            )
        ):
            # Because retry release proves no finding, its family and rule stay blank.
            record(
                {
                    "family": "",
                    "rule": "",
                    "path": "",
                    "outcome": "release",
                    "duration_ms": duration_ms,
                    "turn_id": turn_id,
                }
            )
        return {}

    return run_with_ledger(
        hook="subagent_stop",
        payload=payload,
        gate=gate,
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _scan_message(message: str, cfg: dict) -> list[dict]:
    """Scan only the message because transcript files can be huge."""
    if scannable_text(message, cfg) is None:
        return []
    findings = []
    for finding in scan_all(MESSAGE_PATH, message, cfg):
        item = dict(finding)
        item["path"] = MESSAGE_PATH
        findings.append(item)
    for finding in scan_done_claims(message, MESSAGE_PATH):
        item = dict(finding)
        item["path"] = MESSAGE_PATH
        findings.append(item)
    return findings


def _record_decisions(
    record: Callable[[dict], None],
    turn_id: str,
    decisions: list[tuple[dict, str]],
    duration_ms: int,
) -> None:
    for finding, outcome in decisions:
        record(
            {
                "family": finding["family"],
                "rule": finding["rule"],
                "path": finding["path"],
                "outcome": outcome,
                "duration_ms": duration_ms,
                "turn_id": turn_id,
            }
        )


def _pending_agent_key(agent_id: str) -> str:
    """Use one sentinel for missing IDs and prefix supplied IDs to avoid collision."""
    return f"id:{agent_id}" if agent_id else UNKEYED_AGENT_KEY


def _mark_pending_block(
    session_id: str,
    agent_key: str,
    state_root: str | os.PathLike[str] | None,
) -> None:
    """Add this agent's pending marker under the session lock."""
    try:
        session_state.update_state(
            session_id,
            lambda state: _set_pending_block(state, agent_key),
            state_root,
        )
    except Exception as exc:  # noqa: BLE001 (a state write must never fail a hook)
        sys.stderr.write(
            f"agent-discipline-watcher: pending-block mark failed: {exc}\n"
        )


def _set_pending_block(state: dict, agent_key: str) -> dict:
    pending = state.get(PENDING_BLOCK_KEY)
    markers = dict(pending) if isinstance(pending, dict) else {}
    markers[agent_key] = True
    return {**state, PENDING_BLOCK_KEY: markers}


def _consume_pending_block(
    session_id: str,
    agent_key: str,
    state_root: str | os.PathLike[str] | None,
) -> bool:
    """Consume only this agent's marker under the session lock."""
    found = False

    def mutate(state: dict) -> dict:
        nonlocal found
        pending = state.get(PENDING_BLOCK_KEY)
        markers = dict(pending) if isinstance(pending, dict) else {}
        found = markers.pop(agent_key, None) is not None
        if markers:
            return {**state, PENDING_BLOCK_KEY: markers}
        return {key: value for key, value in state.items() if key != PENDING_BLOCK_KEY}

    try:
        session_state.update_state(session_id, mutate, state_root)
    except Exception as exc:  # noqa: BLE001 (a state write must never fail a hook)
        sys.stderr.write(
            f"agent-discipline-watcher: pending-block consume failed: {exc}\n"
        )
        return False
    return found


if __name__ == "__main__":
    write_payload(run(read_payload()))
