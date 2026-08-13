from __future__ import annotations

import os
import sys

from lib import payloads, session_state
from lib.config import effective_config
from lib.hookio import read_payload, write_payload
from lib.reporting import run_with_ledger

STOP_EVENT = "Stop"


def run(payload: dict, config: dict | None = None) -> dict:
    cfg = effective_config(config, payloads.cwd(payload) or None)
    session_id = payloads.session_id(payload)
    retry = payloads.stop_hook_active(payload)
    if session_id and not retry:
        _advance_turn(session_id, cfg.get("state_root"))

    def gate(_turn_id: str) -> dict:
        return {}

    return run_with_ledger(
        hook="stop",
        payload=payload,
        gate=gate,
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _advance_turn(
    session_id: str, state_root: str | os.PathLike[str] | None
) -> None:
    try:
        session_state.update_state(session_id, _next_turn, state_root)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: turn advance failed: {exc}\n")


def _next_turn(state: dict) -> dict:
    count = state.get("turn_count")
    if not isinstance(count, int) or isinstance(count, bool):
        count = 0
    count += 1
    return {**state, "turn_count": count, "turn_id": f"turn-{count}"}


if __name__ == "__main__":
    write_payload(run(read_payload()))
