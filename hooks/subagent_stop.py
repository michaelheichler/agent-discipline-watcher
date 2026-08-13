from __future__ import annotations

from lib import payloads
from lib.config import effective_hook_config
from lib.end_turn import unresolved_reason
from lib.hookio import PARSE_FAILURE, read_payload, write_payload
from lib.reporting import run_with_ledger

SUBAGENT_STOP_EVENT = "SubagentStop"
STATE_FAILURE = "Agent discipline state could not be verified. Repair the state store before stopping. Cause: "


def run(payload: dict, config: dict | None = None) -> dict:
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload) or not payloads.agent_id(payload):
            return {"decision": "block", "reason": STATE_FAILURE + "invalid SubagentStop payload"}
        cfg = effective_hook_config(config, payloads.cwd(payload) or None)

        def gate(_turn_id: str) -> dict:
            reason = unresolved_reason(payload, cfg)
            return {"decision": "block", "reason": reason} if reason else {}

        return run_with_ledger(
            hook="subagent_stop",
            payload=payload,
            gate=gate,
            ledger_root=cfg.get("ledger_root"),
            state_root=cfg.get("state_root"),
        )
    except Exception as exc:
        return {"decision": "block", "reason": STATE_FAILURE + str(exc)}


if __name__ == "__main__":
    write_payload(run(read_payload()))
