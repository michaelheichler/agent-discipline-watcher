from __future__ import annotations

from lib import payloads, session_state
from lib.config import effective_hook_config
from lib.embedding_session import close_turn, lease_root_for
from lib.end_turn import unresolved_reason
from lib.hookio import PARSE_FAILURE, STATE_FAILURE, read_payload, stop_block, write_payload
from lib.reporting import run_with_ledger

STOP_EVENT = "Stop"


def run(payload: dict, config: dict | None = None) -> dict:
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload):
            return stop_block(STATE_FAILURE + "invalid Stop payload")
        cfg = effective_hook_config(config, payloads.cwd(payload) or None)
        session_id = payloads.session_id(payload)
        retry = payloads.stop_hook_active(payload)
        if session_id and not retry:
            session_state.advance_turn(session_id, cfg.get("state_root"))
            close_turn(session_id, lease_root_for(cfg))

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


if __name__ == "__main__":
    write_payload(run(read_payload()))
