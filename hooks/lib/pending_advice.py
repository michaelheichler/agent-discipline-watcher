"""Stop advice waits for the next prompt, because Codex hands a Stop hook's text to the model only as a block reason."""
from __future__ import annotations

import os

try:
    from . import hookio, session_state
except ImportError:
    import hookio
    import session_state

ADVICE_KEY = "pending_stop_advice"
PROMPT_EVENT = "UserPromptSubmit"
ADVICE_LEAD = "Advice from the last Stop review, not a block."
DROPPED_NOTICE = (
    "agent-discipline-watcher dropped {count} held Stop advice note(s) too large to hand to the model. "
    "The Stop review showed them to you when it ran."
)
MAX_HELD = 4
SEPARATOR = "\n\n"


def hold(session_id: str, advice: str, root: str | os.PathLike[str] | None) -> None:
    def mutate(state: dict) -> dict:
        return {**state, ADVICE_KEY: list(dict.fromkeys([*_held(state), advice]))[-MAX_HELD:]}

    session_state.update_state(session_id, mutate, root)


def _held(state: dict) -> list[str]:
    stored = state.get(ADVICE_KEY)
    return [entry for entry in stored if isinstance(entry, str)] if isinstance(stored, list) else []


def _advised(response: dict, entries: list[str], notice: str) -> dict:
    known = response.get("hookSpecificOutput", {}).get("additionalContext", "")
    advice = SEPARATOR.join([ADVICE_LEAD, *entries]) if entries else ""
    advised = dict(response)
    if advice:
        context = SEPARATOR.join(part for part in (known, advice) if part)
        advised["hookSpecificOutput"] = {"hookEventName": PROMPT_EVENT, "additionalContext": context}
    if notice:
        advised["systemMessage"] = " ".join(part for part in (response.get("systemMessage", ""), notice) if part)
    return advised


def _claim(held: list[str], response: dict) -> tuple[list[str], list[str], str]:
    """Whole entries in order, because a cut entry loses its tail and the agent never sees the rest of that advice."""
    oversized = [entry for entry in held if not hookio.sends_whole(_advised({}, [entry], ""))]
    notice = DROPPED_NOTICE.format(count=len(oversized)) if oversized else ""
    if notice and not hookio.sends_whole(_advised(response, [], notice)):
        notice = ""
    claimed: list[str] = []
    for entry in (entry for entry in held if entry not in oversized):
        if not hookio.sends_whole(_advised(response, [*claimed, entry], notice)):
            break
        claimed.append(entry)
    return claimed, oversized if notice else [], notice


def deliver(session_id: str, root: str | os.PathLike[str] | None, response: dict) -> dict:
    """Claimed under the lock, so that two prompts at once still deliver the advice a single time."""
    if ADVICE_KEY not in session_state.read_state(session_id, root):
        return response
    outcome: list[tuple[list[str], list[str], str]] = []

    def mutate(state: dict) -> dict:
        held = _held(state)
        outcome[:] = [_claim(held, response)]
        claimed, dropped, _notice = outcome[0]
        waiting = [entry for entry in held if entry not in claimed and entry not in dropped]
        rest = {key: value for key, value in state.items() if key != ADVICE_KEY}
        return {**rest, ADVICE_KEY: waiting} if waiting else rest

    session_state.update_state(session_id, mutate, root)
    claimed, _dropped, notice = outcome[0]
    return _advised(response, claimed, notice)
