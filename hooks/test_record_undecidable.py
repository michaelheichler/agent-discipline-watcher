from __future__ import annotations

from pathlib import Path
from unittest import mock

import record
import stop
from lib.config import project_config_path


def _write_payload(tmp_path: Path, target: Path) -> dict:
    return {
        "session_id": "s1",
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_use_id": "t1",
        "tool_input": {"file_path": str(target)},
    }


def _stop_payload(tmp_path: Path) -> dict:
    return {"session_id": "s1", "hook_event_name": "Stop", "cwd": str(tmp_path), "stop_hook_active": False}


def test_record_error_releases_once_stop_rescans_the_unscanned_write_clean(tmp_path: Path) -> None:
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    target = tmp_path / "clean.py"
    target.write_text("x = 1\n", encoding="utf-8")
    with mock.patch.object(record, "_run_record", side_effect=RuntimeError("broken gate")):
        assert record.run(_write_payload(tmp_path, target), config)["decision"] == "block"
    assert stop.run(_stop_payload(tmp_path), config) == {}


def test_record_error_holds_stop_while_the_unscanned_write_has_findings(tmp_path: Path) -> None:
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    target = tmp_path / "dirty.py"
    target.write_text("# Increment the counter.\nx = 1\n", encoding="utf-8")
    with mock.patch.object(record, "_run_record", side_effect=RuntimeError("broken gate")):
        record.run(_write_payload(tmp_path, target), config)
    response = stop.run(_stop_payload(tmp_path), config)
    assert response["decision"] == "block"
    assert (
        "agent-discipline-watcher could not evaluate this edit and blocked it rather than letting it through. "
        f"Repair the gate config at {project_config_path(tmp_path)} and retry. Cause: broken gate"
    ) in response["reason"]
