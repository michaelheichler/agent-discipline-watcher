"""Because a held reviewer verdict blocks every Stop of its turn, it passes the same stall breaker as the Stop rescan, or an agent that cannot change the flagged text never ends the turn."""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import blocker_state, payloads, session_state
from .stop_stall import BlockingSet, StopCall, guarded

HELD_STALL_KEY = "held_stall"
HELD_HOOK = "claude_review"


class Held(NamedTuple):
    texts: list[str]
    notice: str = ""


NONE_HELD = Held([])


def guard(payload: object, texts: list[str], config: dict) -> Held:
    """Counted as own findings, because a held verdict always names text the agent wrote in this turn."""
    session_id = payloads.session_id(payload)
    if not texts or not session_id:
        return Held(texts)
    state_root: str | Path | None = config.get("state_root")
    turn = str(session_state.read_state(session_id, state_root).get("turn_id") or "")
    scope = blocker_state.BlockerScope(session_id, payloads.agent_id(payload), state_root)
    call = StopCall(scope, {**config, "session_id": session_id}, HELD_HOOK, "Stop", turn, HELD_STALL_KEY)
    # Because the turn joins the fingerprint, a later turn counts afresh.
    blocking = BlockingSet([], [*texts, f"turn:{turn}"], owned=True)
    outcome = guarded(call, blocking, lambda _report: ("\n".join(texts), ""))
    return Held(texts if outcome.reason else [], outcome.notice)


def with_notice(response: dict, notice: str) -> dict:
    """Shown to the user, because the release ends the block the agent kept seeing."""
    if not notice:
        return response
    earlier = response.get("systemMessage")
    return {**response, "systemMessage": "\n".join(part for part in (earlier, notice) if part)}
