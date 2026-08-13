from __future__ import annotations

import os

from lib import payloads, session_state
from lib.config import effective_hook_config
from lib.end_turn import unresolved_reason
from lib.hookio import PARSE_FAILURE, read_payload, stop_block, write_payload
from lib.reporting import run_with_ledger

STOP_EVENT = "Stop"
STATE_FAILURE = "Agent discipline state could not be verified. Repair the state store before stopping. Cause: "


def run(payload: dict, config: dict | None = None) -> dict:
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload):
            return stop_block(STATE_FAILURE + "invalid Stop payload")
        cfg = effective_hook_config(config, payloads.cwd(payload) or None)
        session_id = payloads.session_id(payload)
        retry = payloads.stop_hook_active(payload)
        if session_id and not retry:
            _advance_turn(session_id, cfg.get("state_root"))

        def gate(_turn_id: str) -> dict:
            reason = unresolved_reason(payload, cfg)
            return stop_block(reason) if reason else {}

        return run_with_ledger(
            hook="stop",
            payload=payload,
            gate=gate,
            ledger_root=cfg.get("ledger_root"),
            state_root=cfg.get("state_root"),
        )
    except Exception as exc:
        return stop_block(STATE_FAILURE + str(exc))


def _advance_turn(
    session_id: str, state_root: str | os.PathLike[str] | None
) -> None:
    try:
        session_state.update_state_strict(session_id, _next_turn, state_root)
    except Exception as exc:
        raise RuntimeError(f"turn advance failed: {exc}") from exc


def _next_turn(state: dict) -> dict:
    count = state.get("turn_count")
    if not isinstance(count, int) or isinstance(count, bool):
        count = 0
    count += 1
    return {**state, "turn_count": count, "turn_id": f"turn-{count}"}


if __name__ == "__main__":
    write_payload(run(read_payload()))
