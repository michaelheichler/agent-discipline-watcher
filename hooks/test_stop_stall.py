from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

import stop
import subagent_stop
from lib import blocker_state, reporting
from testing import make_repo, run_git

NARRATION = "# Increment the counter.\nx = 1\n"
SECOND = "# Increment the counter.\n# Reset the total.\nx = 1\n"
OWN_STOPS = 5
INHERITED_STOPS = 2

Arranged = tuple[dict, dict]
Arrange = Callable[[Path], Arranged]


def _config(root: Path) -> dict[str, str]:
    return {"ledger_root": str(root / "ledger"), "state_root": str(root / "state")}


def _payload(cwd: Path, agent: str = "") -> dict:
    payload = {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "Stop", "stop_hook_active": False}
    return {**payload, "agent_id": agent} if agent else payload


def _tracked(tmp_path: Path, body: str = NARRATION, agent: str = "") -> Path:
    target = tmp_path / "a.py"
    target.write_text(body, encoding="utf-8")
    blocker_state.touch_paths("s1", agent, [str(target)], _config(tmp_path)["state_root"])
    return target


def _own(tmp_path: Path) -> Arranged:
    _tracked(tmp_path)
    return _payload(tmp_path), _config(tmp_path)


def _committed(tmp_path: Path, current: str) -> Arranged:
    repo = make_repo(tmp_path)
    target = repo / "a.py"
    target.write_text(NARRATION, encoding="utf-8")
    run_git(repo, "add", "a.py")
    run_git(repo, "commit", "-qm", "seed")
    target.write_text(current, encoding="utf-8")
    blocker_state.touch_paths("s1", "", [str(target)], _config(tmp_path)["state_root"])
    return _payload(repo), {**_config(tmp_path), "baseline": "none"}


def _inherited(tmp_path: Path) -> Arranged:
    return _committed(tmp_path, NARRATION)


def _inherited_beside_an_edit(tmp_path: Path) -> Arranged:
    return _committed(tmp_path, NARRATION + "y = 2\n")


def _reworded_inherited(tmp_path: Path) -> Arranged:
    return _committed(tmp_path, NARRATION.replace("counter", "total"))


def _run(arranged: Arranged, count: int) -> list[dict]:
    payload, config = arranged
    return [stop.run(payload, config) for _ in range(count)]


def _stops(tmp_path: Path, count: int) -> list[dict]:
    return _run((_payload(tmp_path), _config(tmp_path)), count)


def _shape(responses: list[dict]) -> list[tuple[str | None, bool]]:
    return [(response.get("decision"), "systemMessage" in response) for response in responses]


def _reports(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "reports").glob("*.json"))


@pytest.mark.parametrize(
    ("arrange", "blocking"),
    [
        (_own, OWN_STOPS), (_inherited, INHERITED_STOPS),
        (_inherited_beside_an_edit, INHERITED_STOPS), (_reworded_inherited, OWN_STOPS),
    ],
    ids=["own finding", "inherited finding", "inherited finding beside an edit", "reworded inherited finding"],
)
def test_an_unchanged_finding_blocks_to_its_limit_then_releases_once(tmp_path: Path, arrange: Arrange, blocking: int) -> None:
    arranged = arrange(tmp_path)

    responses = _run(arranged, blocking + 2)

    assert _shape(responses) == [("block", False)] * blocking + [(None, True), (None, False)]
    assert responses[-1] == {}


def test_the_release_notice_lists_each_unfixed_own_finding_and_the_report(tmp_path: Path) -> None:
    _tracked(tmp_path)

    released = _stops(tmp_path, OWN_STOPS + 1)[-1]["systemMessage"]

    assert "a.py:1 what_comment" in released
    assert str(_reports(tmp_path)[0]) in released


@pytest.mark.parametrize(
    ("arrange", "family"),
    [(_own, "own_finding"), (_inherited, "")],
    ids=["own finding", "inherited finding"],
)
def test_a_release_writes_one_ledger_row_naming_whose_finding(tmp_path: Path, arrange: Arrange, family: str) -> None:
    arranged = arrange(tmp_path)

    _run(arranged, OWN_STOPS + 2)

    rows = reporting.read_jsonl(reporting.LEDGER_FILENAME, _config(tmp_path)["ledger_root"])
    released = [(row["hook"], row["outcome"], row["family"]) for row in rows if row.get("rule") == "stop_stall"]
    assert released == [("stop", "release", family)]


def test_stalled_stop_writes_no_new_report_file(tmp_path: Path) -> None:
    _tracked(tmp_path)

    first, second = _stops(tmp_path, 2)

    assert len(_reports(tmp_path)) == 1
    assert first["reason"] == second["reason"]


def test_stop_blocks_again_after_a_scoped_file_changes(tmp_path: Path) -> None:
    target = _tracked(tmp_path)
    _stops(tmp_path, OWN_STOPS + 2)

    target.write_text(SECOND, encoding="utf-8")

    assert stop.run(_payload(tmp_path), _config(tmp_path))["decision"] == "block"


def test_new_finding_resets_the_stall_count(tmp_path: Path) -> None:
    target = _tracked(tmp_path)
    _stops(tmp_path, OWN_STOPS)
    target.write_text(SECOND, encoding="utf-8")

    responses = _stops(tmp_path, OWN_STOPS + 1)

    assert _shape(responses) == [("block", False)] * OWN_STOPS + [(None, True)]


def test_a_pathless_pending_block_stalls_too(tmp_path: Path) -> None:
    blocker_state.set_pending("s1", "", "<batch-error>", "Repair batch evaluation", _config(tmp_path)["state_root"])

    responses = _stops(tmp_path, 3)

    assert [response.get("decision") for response in responses] == ["block", "block", None]
    assert "repeated 2 times" in responses[2]["systemMessage"]


def test_subagent_stop_uses_the_same_breaker(tmp_path: Path) -> None:
    _tracked(tmp_path, agent="agent-7")
    payload = {**_payload(tmp_path, "agent-7"), "hook_event_name": "SubagentStop"}

    responses = [subagent_stop.run(payload, _config(tmp_path)) for _ in range(OWN_STOPS + 2)]

    assert _shape(responses) == [("block", False)] * OWN_STOPS + [(None, True), (None, False)]
    assert responses[-1] == {}


def test_the_limit_is_configurable(tmp_path: Path) -> None:
    blocker_state.set_pending("s1", "", "<batch-error>", "Repair batch evaluation", _config(tmp_path)["state_root"])
    config = {**_config(tmp_path), "stop_stall_limit": 1}

    responses = [stop.run(_payload(tmp_path), config) for _ in range(2)]

    assert _shape(responses) == [("block", False), (None, True)]


def test_a_lower_configured_limit_does_not_shorten_the_own_finding_limit(tmp_path: Path) -> None:
    _tracked(tmp_path)
    config = {**_config(tmp_path), "stop_stall_limit": 1}

    responses = [stop.run(_payload(tmp_path), config) for _ in range(OWN_STOPS + 1)]

    assert _shape(responses) == [("block", False)] * OWN_STOPS + [(None, True)]
