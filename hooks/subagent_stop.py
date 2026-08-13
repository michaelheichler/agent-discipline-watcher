from __future__ import annotations

from lib import payloads
from lib.config import effective_config
from lib.hookio import read_payload, write_payload
from lib.reporting import run_with_ledger

SUBAGENT_STOP_EVENT = "SubagentStop"


def run(payload: dict, config: dict | None = None) -> dict:
    cfg = effective_config(config, payloads.cwd(payload) or None)

    def gate(_turn_id: str) -> dict:
        return {}

    return run_with_ledger(
        hook="subagent_stop",
        payload=payload,
        gate=gate,
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


if __name__ == "__main__":
    write_payload(run(read_payload()))
