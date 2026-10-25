"""Because the type record lives in session state for the whole session, it must stay bounded and drop the oldest agent first."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import agent_types


def started(agent_id: str) -> dict:
    return {"session_id": "s1", "hook_event_name": "SubagentStart", "agent_id": agent_id, "agent_type": "Explore"}


@pytest.mark.parametrize(("agent_id", "expected"), [
    pytest.param("agent-0", "", id="oldest-forgotten"),
    pytest.param("agent-1", "Explore", id="next-oldest-kept"),
])
def test_the_record_drops_the_oldest_agent_once_past_its_cap(tmp_path: Path, agent_id: str, expected: str) -> None:
    for index in range(agent_types.MAX_AGENTS + 1):
        agent_types.remember(started(f"agent-{index}"), tmp_path)

    assert agent_types.type_of({"session_id": "s1", "agent_id": agent_id}, tmp_path) == expected
