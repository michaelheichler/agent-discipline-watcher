from __future__ import annotations

from collections.abc import Callable

from lib import adw_copies, retention, session_state, turn_adapter
from lib.hookio import CONTRACT, CONTRACT_REMINDER, context, read_payload, write_payload

SESSION_START_EVENT = "SessionStart"
REMINDER_SOURCES = frozenset({"resume", "clear", "compact"})


def run(payload: dict | None = None, config: dict | None = None, *, drift: Callable[[], str] | None = None) -> dict:
    """Send the full contract once per startup and a one-line reminder after, because the model already holds the rules."""
    fields = payload if isinstance(payload, dict) else {}
    session_id = fields.get("session_id")
    settings = config if isinstance(config, dict) else {}
    if isinstance(session_id, str) and session_id:
        state_root = settings.get("state_root") if isinstance(settings.get("state_root"), str) else None
        ledger_root = settings.get("ledger_root") if isinstance(settings.get("ledger_root"), str) else None
        session_state.acquire_session_lease(session_id, state_root)
        retention.sweep(state_root=state_root, ledger_root=ledger_root)
    live_session = session_id if isinstance(session_id, str) else ""
    turn_adapter.prepare_session(session_id=live_session, config=settings)
    message = CONTRACT_REMINDER if fields.get("source") in REMINDER_SOURCES else CONTRACT
    notice = (drift or _drift_notice)()
    return {**context(message, SESSION_START_EVENT), **({"systemMessage": notice} if notice else {})}


def _drift_notice() -> str:
    """Told to the user and not the model, because only the user can remove a copy from the host that installed it."""
    try:
        return adw_copies.notice(adw_copies.stale())
    except (OSError, RuntimeError, ValueError):
        return ""


if __name__ == "__main__":
    write_payload(run(read_payload()))
