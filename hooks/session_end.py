from __future__ import annotations

from lib import payloads, session_state
from lib.config import effective_hook_config
from lib.hookio import read_payload, write_payload


def run(payload: dict, config: dict | None = None) -> dict:
    session_id = payloads.session_id(payload)
    if not session_id:
        return {}
    state_root = None
    try:
        cfg = effective_hook_config(config, payloads.cwd(payload) or None)
        state_root = cfg.get("state_root")
    except Exception:
        pass
    try:
        session_state.release_session_lease(session_id, state_root)
    except Exception:
        pass
    return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
