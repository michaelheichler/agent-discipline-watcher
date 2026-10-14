from __future__ import annotations

from lib import payloads, session_state
from lib.config import payload_hook_config
from lib.end_turn import stop_outcome
from lib.hookio import PARSE_FAILURE, STATE_FAILURE, read_payload, stop_block, system_message, write_payload
from lib.reporting import run_with_ledger

SUBAGENT_STOP_EVENT = "SubagentStop"


def run(payload: dict, config: dict | None = None) -> dict:
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload) or not payloads.agent_id(payload):
            return stop_block(STATE_FAILURE + "invalid SubagentStop payload")
        cfg = payload_hook_config(config, payload)

        def gate(turn_id: str) -> dict:
            outcome = stop_outcome(payload, cfg, hook="subagent_stop", turn_id=turn_id)
            notice = "\n".join(part for part in (
                session_state.take_recovery_notice(payloads.session_id(payload), cfg.get("state_root")), outcome.notice,
            ) if part)
            response = system_message(notice) if notice else {}
            return {**stop_block(outcome.reason), **response} if outcome.reason else response

        return run_with_ledger(
            hook="subagent_stop",
            payload=payload,
            gate=gate,
            ledger_root=cfg.get("ledger_root"),
            state_root=cfg.get("state_root"),
        )
    except Exception as exc:
        return stop_block(STATE_FAILURE + str(exc))


if __name__ == "__main__":
    write_payload(run(read_payload()))
