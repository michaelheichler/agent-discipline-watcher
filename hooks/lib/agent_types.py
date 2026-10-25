"""Because a later hook payload can carry the agent id without the type, SubagentStart keeps the type by id."""
from __future__ import annotations

from pathlib import Path

try:
    from . import payloads, session_state
except ImportError:
    import payloads
    import session_state

STATE_KEY = "agent_types"
MAX_AGENTS = 200


def remember(payload: object, state_root: str | Path | None) -> None:
    """Taken from SubagentStart only, because the host sets that payload when it starts the agent."""
    session_id, agent_id, agent_type = payloads.session_id(payload), payloads.agent_id(payload), payloads.agent_type(payload)
    if not (session_id and agent_id and agent_type):
        return

    def update(state: dict) -> dict:
        known = _known(state)
        known.pop(agent_id, None)
        kept = dict(list(known.items())[-(MAX_AGENTS - 1):])
        return {**state, STATE_KEY: {**kept, agent_id: agent_type}}

    session_state.update_state(session_id, update, state_root)


def type_of(payload: object, state_root: str | Path | None) -> str:
    """The payload type first, because the host states it for the call at hand."""
    stated = payloads.agent_type(payload)
    agent_id, session_id = payloads.agent_id(payload), payloads.session_id(payload)
    if stated or not (agent_id and session_id):
        return stated
    try:
        return _known(session_state.read_state(session_id, state_root)).get(agent_id, "")
    except (OSError, ValueError):
        return ""


def _known(state: dict) -> dict[str, str]:
    stored = state.get(STATE_KEY)
    if type(stored) is not dict:
        return {}
    return {key: value for key, value in stored.items() if type(key) is str and type(value) is str}
