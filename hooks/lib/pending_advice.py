"""Stop advice waits for the next prompt, because Codex hands a Stop hook's text to the model only as a block reason."""
from __future__ import annotations

import os

try:
    from . import session_state
except ImportError:
    import session_state

ADVICE_KEY = "pending_stop_advice"
ADVICE_LEAD = "Advice from the last Stop review, not a block."
MAX_HELD = 4


def hold(session_id: str, advice: str, root: str | os.PathLike[str] | None) -> None:
    def mutate(state: dict) -> dict:
        stored = state.get(ADVICE_KEY)
        held = [entry for entry in stored if isinstance(entry, str)] if isinstance(stored, list) else []
        return {**state, ADVICE_KEY: list(dict.fromkeys([*held, advice]))[-MAX_HELD:]}

    session_state.update_state(session_id, mutate, root)


def take(session_id: str, root: str | os.PathLike[str] | None) -> str:
    """Claimed under the lock, so that two prompts at once still deliver the advice a single time."""
    if ADVICE_KEY not in session_state.read_state(session_id, root):
        return ""
    claimed: list[str] = []

    def mutate(state: dict) -> dict:
        stored = state.get(ADVICE_KEY)
        if isinstance(stored, list):
            claimed.extend(entry for entry in stored if isinstance(entry, str))
        return {key: value for key, value in state.items() if key != ADVICE_KEY}

    session_state.update_state(session_id, mutate, root)
    return "\n\n".join([ADVICE_LEAD, *claimed]) if claimed else ""
