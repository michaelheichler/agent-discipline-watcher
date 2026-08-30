"""Kept in the core because a turn recorded under one host still needs clearing when the marker is gone."""
from __future__ import annotations

from pathlib import Path

try:
    from . import session_state
except ImportError:
    import session_state


RETRY_KEY = "codex_luna_retry_turn"


def retry_turn_id(session_id: str, state_root: str | Path | None) -> str:
    """Answer with an empty string on a broken read because a missing retry must not block the turn."""
    try:
        value = session_state.read_state(session_id, state_root).get(RETRY_KEY)
    except (OSError, ValueError, TypeError):
        return ""
    return value if isinstance(value, str) and value else ""


def clear_retry_identity(session_id: str, state_root: str | Path | None) -> None:
    """Swallow a failure here because session end must release state rather than raise on the way out."""
    def update(state: dict) -> dict:
        return {key: value for key, value in state.items() if key != RETRY_KEY}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        pass
