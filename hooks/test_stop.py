from __future__ import annotations

from pathlib import Path
from unittest import mock

import stop
from lib import blocker_state, reporting, session_state


def _config(root: Path) -> dict[str, str]:
    return {
        "ledger_root": str(root / "ledger"),
        "state_root": str(root / "state"),
    }


def _payload(retry: bool = False) -> dict:
    return {
        "session_id": "s1",
        "hook_event_name": "Stop",
        "last_assistant_message": "unscanned" + chr(0x2014) + "message",
        "stop_hook_active": retry,
    }


def test_stop_advances_the_turn_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert stop.run(_payload(), config) == {}
    assert session_state.read_state("s1", config["state_root"])["turn_id"] == "turn-1"


def test_stop_retry_does_not_advance_again(tmp_path: Path) -> None:
    config = _config(tmp_path)
    stop.run(_payload(), config)
    stop.run(_payload(retry=True), config)
    assert session_state.read_state("s1", config["state_root"])["turn_count"] == 1


def test_stop_records_a_heartbeat_without_scanning_chat(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert stop.run(_payload(), config) == {}
    rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, config["ledger_root"])
    assert [(row["hook"], row["event"]) for row in rows] == [("stop", "observed")]


def test_stop_blocks_termination_until_pending_denial_clears(tmp_path: Path) -> None:
    config = _config(tmp_path)
    blocker_state.set_pending("s1", "", "a.py", "Fix a.py", config["state_root"])
    assert stop.run(_payload(), config) == {"decision": "block", "reason": "Fix a.py"}
    blocker_state.clear_pending("s1", "", "a.py", config["state_root"])
    assert stop.run(_payload(retry=True), config) == {}


def test_stop_keeps_undecidable_batch_pending_without_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    blocker_state.set_pending("s1", "", "<batch>", "Repair the batch gate", config["state_root"])
    assert stop.run(_payload(), config) == {
        "decision": "block",
        "reason": "Repair the batch gate",
    }


def test_stop_rescans_touched_file_and_allows_clean_retry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    target = tmp_path / "a.py"
    target.write_text("# Increment the counter.\nx = 1\n", encoding="utf-8")
    blocker_state.touch_paths("s1", "", [str(target)], config["state_root"])
    response = stop.run({**_payload(), "cwd": str(tmp_path)}, config)
    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]
    target.write_text("# Explicit because callers inspect module state\nx = 1\n", encoding="utf-8")
    assert stop.run({**_payload(True), "cwd": str(tmp_path)}, config) == {}


def test_stop_rechecks_oversized_file_when_text_scan_is_capped(tmp_path: Path) -> None:
    config = {**_config(tmp_path), "max_scan_bytes": 10}
    target = tmp_path / "large.py"
    target.write_text("x = 1\n" * 1000, encoding="utf-8")
    blocker_state.touch_paths("s1", "", [str(target)], config["state_root"])
    response = stop.run({**_payload(), "cwd": str(tmp_path)}, config)
    assert response["decision"] == "block"
    assert "file_too_long" in response["reason"]


def test_project_config_cannot_redirect_stop_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    redirected = tmp_path / "redirected"
    (tmp_path / ".agent-discipline.json").write_text(
        '{"state_root":"' + str(redirected) + '"}', encoding="utf-8",
    )
    blocker_state.set_pending("s1", "", "<batch>", "Fix trusted state", config["state_root"])
    response = stop.run({**_payload(), "cwd": str(project)}, config)
    assert response["reason"] == "Fix trusted state"
    assert not redirected.exists()


def test_stop_blocks_when_state_cannot_be_read(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with mock.patch.object(blocker_state, "scope_ids", side_effect=OSError("read only")):
        response = stop.run(_payload(), config)
    assert response["decision"] == "block"
    assert "state could not be verified" in response["reason"]


def test_stop_keeps_undecidable_batch_pending_after_clean_path_scan(tmp_path: Path) -> None:
    config = _config(tmp_path)
    target = tmp_path / "clean.py"
    target.write_text("x = 1\n", encoding="utf-8")
    blocker_state.touch_paths("s1", "", [str(target)], config["state_root"])
    blocker_state.set_pending(
        "s1", "", "<batch-error>", "Repair batch evaluation", config["state_root"],
    )
    response = stop.run({**_payload(), "cwd": str(tmp_path)}, config)
    assert response == {"decision": "block", "reason": "Repair batch evaluation"}


def test_parent_stop_aggregates_subagent_blockers(tmp_path: Path) -> None:
    config = _config(tmp_path)
    blocker_state.set_pending("s1", "agent-7", "<batch-error>", "Fix subagent batch", config["state_root"])
    assert stop.run(_payload(), config) == {
        "decision": "block",
        "reason": "Fix subagent batch",
    }


def test_stop_blocks_malformed_payload(tmp_path: Path) -> None:
    response = stop.run({"_parse_failure": True}, _config(tmp_path))
    assert response["decision"] == "block"


def test_stop_blocks_corrupt_state_without_replacing_it(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_file = Path(config["state_root"]) / "s1" / "state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("not-json", encoding="utf-8")
    response = stop.run(_payload(), config)
    assert response["decision"] == "block"
    assert state_file.read_text(encoding="utf-8") == "not-json"
