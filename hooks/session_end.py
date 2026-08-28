from __future__ import annotations

from lib import payloads, session_state
from lib.config import effective_hook_config
from lib.hookio import PARSE_FAILURE, STATE_FAILURE, read_payload, stop_block, write_payload


def run(payload: dict, config: dict | None = None) -> dict:
    try:
        if payload is PARSE_FAILURE or not payloads.session_id(payload):
            return stop_block(STATE_FAILURE + "invalid SessionEnd payload")
        cfg = effective_hook_config(config, payloads.cwd(payload) or None)
        session_state.release_session_lease(
            payloads.session_id(payload), cfg.get("state_root")
        )
        return {}
    except Exception as exc:
        return stop_block(STATE_FAILURE + str(exc))


if __name__ == "__main__":
    write_payload(run(read_payload()))
