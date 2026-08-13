from __future__ import annotations

from pathlib import Path
from unittest import mock

import stop
import subagent_stop
from lib import blocker_state, reporting, session_state


def _config(root: Path) -> dict[str, str]:
    return {
        "ledger_root": str(root / "ledger"),
        "state_root": str(root / "state"),
    }


def _payload() -> dict:
    return {
        "session_id": "s1",
        "hook_event_name": "SubagentStop",
        "agent_type": "python-engineer",
        "agent_id": "agent-7",
        "last_assistant_message": "unscanned" + chr(0x2014) + "message",
    }


def test_subagent_stop_does_not_create_a_parent_turn(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert subagent_stop.run(_payload(), config) == {}
    assert "turn_count" not in session_state.read_state("s1", config["state_root"])


def test_subagent_stop_uses_the_parent_turn(tmp_path: Path) -> None:
    config = _config(tmp_path)
    stop.run({"session_id": "s1", "stop_hook_active": False}, config)
    assert subagent_stop.run(_payload(), config) == {}
    rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, config["ledger_root"])
    subagent_rows = [row for row in rows if row["hook"] == "subagent_stop"]
    assert subagent_rows[0]["turn_id"] == "turn-1"


def test_subagent_stop_checks_only_its_own_blockers(tmp_path: Path) -> None:
    config = _config(tmp_path)
    blocker_state.set_pending("s1", "agent-7", "a.py", "Fix subagent file", config["state_root"])
    blocker_state.set_pending("s1", "", "parent.py", "Fix parent file", config["state_root"])
    assert subagent_stop.run(_payload(), config) == {
        "decision": "block",
        "reason": "Fix subagent file",
    }


def test_subagent_stop_blocks_when_state_cannot_be_read(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with mock.patch.object(blocker_state, "details", side_effect=OSError("read only")):
        response = subagent_stop.run(_payload(), config)
    assert response["decision"] == "block"
    assert "state could not be verified" in response["reason"]


def test_subagent_stop_blocks_malformed_payload(tmp_path: Path) -> None:
    response = subagent_stop.run({"_parse_failure": True}, _config(tmp_path))
    assert response["decision"] == "block"
