from __future__ import annotations

from typing import Callable, NamedTuple

from lib import host, payloads, session_state, turn_adapter, turn_retry
from lib.config import payload_hook_config
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


class _StopTurn(NamedTuple):
    payload: dict
    cfg: dict
    adapter: turn_adapter.TurnAdapter
    provider: object | None
    known_turn_id: str


def _verdict(payload: dict, cfg: dict) -> dict:
    reason = unresolved_reason(payload, cfg)
    if reason:
        return stop_block(reason)
    if host.is_codex_host():
        return {}
    notice = foreign_scope_notice(payload, cfg)
    return system_message(notice) if notice else {}


def _closed_turn_id(session_id: str, cfg: dict, retry: bool) -> str:
    """Read before advancing, because review needs the old turn."""
    if retry:
        return ""
    value = session_state.read_state(session_id, cfg.get("state_root")).get("turn_id")
    session_state.advance_turn(session_id, cfg.get("state_root"))
    close_turn(session_id, lease_root_for(cfg))
    return value if isinstance(value, str) else ""


def _gate(turn: _StopTurn) -> Callable[[str], dict]:
    def gate(turn_id: str) -> dict:
        verdict = _verdict(turn.payload, turn.cfg)
        if verdict.get("decision") == "block" or not turn.adapter.reviews_turns:
            return verdict
        reviewed = turn.adapter.review(
            turn.payload,
            turn_id=turn.known_turn_id or turn_id,
            state_root=turn.cfg.get("state_root"),
            provider=turn.provider,
        )
        if reviewed.get("decision") == "block":
            return reviewed
        return {**verdict, **reviewed} if reviewed else verdict

    return gate


def _run(payload: dict, config: dict | None, provider: object | None) -> dict:
    cfg = payload_hook_config(config, payload)
    session_id = payloads.session_id(payload)
    adapter = turn_adapter.for_turn(injected_provider=provider is not None)
    retry_turn_id = turn_retry.retry_turn_id(session_id, cfg.get("state_root"))
    state_turn_id = _closed_turn_id(session_id, cfg, payloads.stop_hook_active(payload))
    known = payloads.turn_id(payload) or retry_turn_id or state_turn_id
    return run_with_ledger(
        hook="stop",
        payload=payload,
        gate=_gate(_StopTurn(payload, cfg, adapter, provider, known)),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def run(
    payload: dict,
    config: dict | None = None,
    *,
    provider: object | None = None,
) -> dict:
    """Block on failure, because a broken Stop must not release."""
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload):
            return stop_block(STATE_FAILURE + "invalid Stop payload")
        return _run(payload, config, provider)
    except Exception as exc:
        return stop_block(STATE_FAILURE + str(exc))


if __name__ == "__main__":
    write_payload(run(read_payload()))
