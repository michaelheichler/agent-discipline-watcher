from __future__ import annotations

from lib import retention, session_state
from lib.hookio import CONTRACT, context, read_payload, write_payload

SESSION_START_EVENT = "SessionStart"
def run(payload: dict | None = None, config: dict | None = None) -> dict:
    """Provide one bounded contract through the host model channel."""
    fields = payload if isinstance(payload, dict) else {}
    session_id = fields.get("session_id")
    if isinstance(session_id, str) and session_id:
        settings = config if isinstance(config, dict) else {}
        state_root = settings.get("state_root") if isinstance(settings.get("state_root"), str) else None
        ledger_root = settings.get("ledger_root") if isinstance(settings.get("ledger_root"), str) else None
        session_state.acquire_session_lease(session_id, state_root)
        retention.sweep(state_root=state_root, ledger_root=ledger_root)
    return context(CONTRACT, SESSION_START_EVENT)


if __name__ == "__main__":
    write_payload(run(read_payload()))
