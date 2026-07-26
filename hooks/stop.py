"""Stop gate: scan the final assistant message and close out the session turn."""
from __future__ import annotations

import os
import sys
import time

from lib import payloads, session_state
from lib.config import effective_config, resolve_outcome
from lib.done_claims import scan_done_claims
from lib.hookio import read_payload, stop_block, write_payload
from lib.reporting import compact_block, record_decision, run_with_ledger
from lib.scanner import scan_all, scannable_text

MESSAGE_PATH = "last_assistant_message.md"
STOP_EVENT = "Stop"
PENDING_BLOCK_KEY = "pending_stop_block"


def run(payload: dict, config: dict | None = None) -> dict:
    cfg = effective_config(config, payloads.cwd(payload) or None)
    session_id = payloads.session_id(payload)
    retry = payloads.stop_hook_active(payload)
    # Advance only on the first Stop because stop_hook_active marks a re-invocation of one turn.
    if session_id and not retry:
        _advance_turn(session_id, cfg.get("state_root"))

    def gate(turn_id: str) -> dict:
        started = time.monotonic()
        findings = _scan_message(payloads.last_assistant_message(payload), cfg)
        decisions = [(finding, resolve_outcome(finding, cfg)) for finding in findings]
        duration_ms = int((time.monotonic() - started) * 1000)
        if session_id:
            _record_decisions(session_id, turn_id, decisions, duration_ms, cfg)
        blocking = [finding for finding, outcome in decisions if outcome == "block"]
        if blocking:
            if session_id:
                _mark_pending_block(session_id, cfg.get("state_root"))
            reason, _ = compact_block(blocking, cfg)
            return stop_block(reason)
        if (
            retry
            and session_id
            and _consume_pending_block(session_id, cfg.get("state_root"))
        ):
            # Blank family and rule because this release proves the retry exited, not a finding.
            record_decision(
                session_id=session_id, hook="stop", event=STOP_EVENT,
                family="", rule="", path="", tool_use_id="",
                outcome="release", duration_ms=duration_ms,
                turn_id=turn_id, root=cfg.get("ledger_root"),
            )
        return {}

    return run_with_ledger(
        hook="stop",
        payload=payload,
        gate=gate,
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _scan_message(message: str, cfg: dict) -> list[dict]:
    """Scan the final message with the scanner families plus the unproved-done rule."""
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
    session_id: str,
    turn_id: str,
    decisions: list[tuple[dict, str]],
    duration_ms: int,
    cfg: dict,
) -> None:
    for finding, outcome in decisions:
        record_decision(
            session_id=session_id, hook="stop", event=STOP_EVENT,
            family=finding["family"], rule=finding["rule"],
            path=finding["path"], tool_use_id="", outcome=outcome,
            duration_ms=duration_ms, turn_id=turn_id,
            root=cfg.get("ledger_root"),
        )


def _advance_turn(session_id: str, state_root: str | os.PathLike[str] | None) -> None:
    """Move the session to the next turn, swallowing state errors so the hook never fails."""
    try:
        session_state.update_state(session_id, _next_turn, state_root)
    except Exception as exc:  # noqa: BLE001 (a state write must never fail a hook)
        sys.stderr.write(f"agent-discipline-watcher: turn advance failed: {exc}\n")


def _next_turn(state: dict) -> dict:
    count = state.get("turn_count")
    if not isinstance(count, int) or isinstance(count, bool):
        count = 0
    count += 1
    return {**state, "turn_count": count, "turn_id": f"turn-{count}"}


def _mark_pending_block(
    session_id: str, state_root: str | os.PathLike[str] | None
) -> None:
    """Flag the block in session state because a retry release must be state-proved."""
    try:
        session_state.update_state(session_id, _set_pending_block, state_root)
    except Exception as exc:  # noqa: BLE001 (a state write must never fail a hook)
        sys.stderr.write(
            f"agent-discipline-watcher: pending-block mark failed: {exc}\n"
        )


def _set_pending_block(state: dict) -> dict:
    return {**state, PENDING_BLOCK_KEY: True}


def _consume_pending_block(
    session_id: str, state_root: str | os.PathLike[str] | None
) -> bool:
    """Clear the pending-block flag under the session lock, returning True only if it was set."""
    found = False

    def mutate(state: dict) -> dict:
        nonlocal found
        found = bool(state.get(PENDING_BLOCK_KEY))
        return {
            key: value for key, value in state.items() if key != PENDING_BLOCK_KEY
        }

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
