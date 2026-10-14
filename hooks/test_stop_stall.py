from __future__ import annotations

from pathlib import Path

import stop
import subagent_stop
from lib import blocker_state, reporting

NARRATION = "# Increment the counter.\nx = 1\n"
SECOND = "# Increment the counter.\n# Reset the total.\nx = 1\n"


def _config(root: Path) -> dict[str, str]:
    return {"ledger_root": str(root / "ledger"), "state_root": str(root / "state")}


def _payload(tmp_path: Path, agent: str = "") -> dict:
    payload = {"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "Stop", "stop_hook_active": False}
    return {**payload, "agent_id": agent} if agent else payload


def _tracked(tmp_path: Path, body: str = NARRATION, agent: str = "") -> Path:
    target = tmp_path / "a.py"
    target.write_text(body, encoding="utf-8")
    blocker_state.touch_paths("s1", agent, [str(target)], _config(tmp_path)["state_root"])
    return target


def _stops(tmp_path: Path, count: int) -> list[dict]:
    return [stop.run(_payload(tmp_path), _config(tmp_path)) for _ in range(count)]


def _reports(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "reports").glob("*.json"))


def test_stop_blocks_up_to_the_limit_then_releases_with_one_notice(tmp_path: Path) -> None:
    _tracked(tmp_path)

    first, second, third = _stops(tmp_path, 3)

    assert first["decision"] == second["decision"] == "block"
    assert "decision" not in third
    assert "unchanged since the last 2 Stops" in third["systemMessage"]
    assert "a.py" in third["systemMessage"]
    assert str(_reports(tmp_path)[0]) in third["systemMessage"]


def test_stall_notice_is_sent_once_then_silent(tmp_path: Path) -> None:
    _tracked(tmp_path)

    responses = _stops(tmp_path, 5)

    assert [("systemMessage" in response) for response in responses] == [False, False, True, False, False]
    assert responses[3] == responses[4] == {}


def test_stalled_stop_writes_no_new_report_file(tmp_path: Path) -> None:
    _tracked(tmp_path)

    first, second = _stops(tmp_path, 2)

    assert len(_reports(tmp_path)) == 1
    assert first["reason"] == second["reason"]


def test_stop_blocks_again_after_a_scoped_file_changes(tmp_path: Path) -> None:
    target = _tracked(tmp_path)
    _stops(tmp_path, 4)

    target.write_text(SECOND, encoding="utf-8")

    assert stop.run(_payload(tmp_path), _config(tmp_path))["decision"] == "block"


def test_new_finding_resets_the_stall_count(tmp_path: Path) -> None:
    target = _tracked(tmp_path)
    _stops(tmp_path, 2)
    target.write_text(SECOND, encoding="utf-8")

    first, second, third = _stops(tmp_path, 3)

    assert first["decision"] == second["decision"] == "block"
    assert "systemMessage" in third


def test_a_pathless_pending_block_stalls_too(tmp_path: Path) -> None:
    blocker_state.set_pending("s1", "", "<batch-error>", "Repair batch evaluation", _config(tmp_path)["state_root"])

    responses = _stops(tmp_path, 3)

    assert [response.get("decision") for response in responses] == ["block", "block", None]
    assert "repeated 2 times" in responses[2]["systemMessage"]


def test_subagent_stop_uses_the_same_breaker(tmp_path: Path) -> None:
    _tracked(tmp_path, agent="agent-7")
    payload = {**_payload(tmp_path, "agent-7"), "hook_event_name": "SubagentStop"}

    responses = [subagent_stop.run(payload, _config(tmp_path)) for _ in range(4)]

    assert [response.get("decision") for response in responses] == ["block", "block", None, None]
    assert "Not blocking again" in responses[2]["systemMessage"]
    assert responses[3] == {}


def test_stall_release_writes_a_ledger_row(tmp_path: Path) -> None:
    _tracked(tmp_path)

    _stops(tmp_path, 4)

    rows = reporting.read_jsonl(reporting.LEDGER_FILENAME, _config(tmp_path)["ledger_root"])
    released = [row for row in rows if row.get("rule") == "stop_stall"]
    assert [(row["hook"], row["outcome"]) for row in released] == [("stop", "release")]


def test_the_limit_is_configurable(tmp_path: Path) -> None:
    _tracked(tmp_path)
    config = {**_config(tmp_path), "stop_stall_limit": 1}

    first, second = (stop.run(_payload(tmp_path), config) for _ in range(2))

    assert first["decision"] == "block"
    assert "Not blocking again" in second["systemMessage"]
