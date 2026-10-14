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
SEPARATOR = "\n\n"


def hold(session_id: str, advice: str, root: str | os.PathLike[str] | None) -> None:
    def mutate(state: dict) -> dict:
        stored = state.get(ADVICE_KEY)
        held = [entry for entry in stored if isinstance(entry, str)] if isinstance(stored, list) else []
        return {**state, ADVICE_KEY: list(dict.fromkeys([*held, advice]))[-MAX_HELD:]}

    session_state.update_state(session_id, mutate, root)


def _fitting(held: list[str], budget: int) -> list[str]:
    """Whole entries in order, because a cut entry loses its tail and the agent never sees the rest of that advice."""
    used = len(ADVICE_LEAD)
    fitting: list[str] = []
    for entry in held:
        used += len(SEPARATOR) + len(entry)
        if used > budget:
            break
        fitting.append(entry)
    return fitting


def take(session_id: str, root: str | os.PathLike[str] | None, budget: int) -> str:
    """Claimed under the lock, so that two prompts at once still deliver the advice a single time."""
    if ADVICE_KEY not in session_state.read_state(session_id, root):
        return ""
    claimed: list[str] = []

    def mutate(state: dict) -> dict:
        stored = state.get(ADVICE_KEY)
        held = [entry for entry in stored if isinstance(entry, str)] if isinstance(stored, list) else []
        claimed[:] = _fitting(held, budget)
        rest = {key: value for key, value in state.items() if key != ADVICE_KEY}
        return {**rest, ADVICE_KEY: held[len(claimed):]} if len(claimed) < len(held) else rest

    session_state.update_state(session_id, mutate, root)
    return SEPARATOR.join([ADVICE_LEAD, *claimed]) if claimed else ""
