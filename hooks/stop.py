from __future__ import annotations

import os

from lib import payloads, session_state
from lib import codex_luna
from lib.config import effective_hook_config
from lib.embedding_session import close_turn, lease_root_for
from lib.end_turn import foreign_scope_notice, unresolved_reason
from lib.hookio import (
    PARSE_FAILURE,
    STATE_FAILURE,
    read_payload,
    stop_block,
    system_message,
    write_payload,
)
from lib.reporting import run_with_ledger

STOP_EVENT = "Stop"


def _verdict(payload: dict, cfg: dict) -> dict:
    reason = unresolved_reason(payload, cfg)
    if reason:
        return stop_block(reason)
    if os.environ.get("ADW_CODEX_HOOK") == "1":
        return {}
    notice = foreign_scope_notice(payload, cfg)
    return system_message(notice) if notice else {}


def run(
    payload: dict,
    config: dict | None = None,
    *,
    provider: object | None = None,
) -> dict:
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload):
            return stop_block(STATE_FAILURE + "invalid Stop payload")
        cfg = effective_hook_config(config, payloads.cwd(payload) or None)
        session_id = payloads.session_id(payload)
        retry = payloads.stop_hook_active(payload)
        host_turn_id = payloads.turn_id(payload)
        retry_turn_id = codex_luna.retry_turn_id(session_id, cfg.get("state_root"))
        state_turn_id = ""
        if session_id and not retry:
            state = session_state.read_state(session_id, cfg.get("state_root"))
            value = state.get("turn_id")
            state_turn_id = value if isinstance(value, str) else ""
        if session_id and not retry:
            session_state.advance_turn(session_id, cfg.get("state_root"))
            close_turn(session_id, lease_root_for(cfg))

        codex_mode = os.environ.get("ADW_CODEX_HOOK") == "1" or provider is not None

        def gate(turn_id: str) -> dict:
            verdict = _verdict(payload, cfg)
            if verdict.get("decision") == "block":
                return verdict
            if codex_mode:
                reviewed = codex_luna.review(
                    payload,
                    turn_id=host_turn_id or retry_turn_id or state_turn_id or turn_id,
                    state_root=cfg.get("state_root"),
                    provider=provider,
                )
                if reviewed.get("decision") == "block":
                    return reviewed
            return verdict

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
