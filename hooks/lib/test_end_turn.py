from __future__ import annotations

from pathlib import Path

from lib import blocker_state, end_turn


def _held_record_error(tmp_path: Path, target: Path) -> dict:
    payload = {
        "session_id": "s1",
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    blocker_state.hold_undecidable(
        payload, {"state_root": str(tmp_path / "state")}, blocker_state.RECORD_ERROR_KEY, "Repair the record gate",
    )
    return payload


def test_record_error_clears_when_every_touched_path_rescans_clean(tmp_path: Path) -> None:
    target = tmp_path / "clean.py"
    target.write_text("x = 1\n", encoding="utf-8")
    payload = _held_record_error(tmp_path, target)
    cfg = {"state_root": str(tmp_path / "state")}
    assert end_turn.unresolved_reason(payload, cfg) == ""
    assert blocker_state.details("s1", "", cfg["state_root"])[0] == {}


def test_record_error_stays_while_a_touched_path_still_has_findings(tmp_path: Path) -> None:
    target = tmp_path / "dirty.py"
    target.write_text("# Increment the counter.\nx = 1\n", encoding="utf-8")
    payload = _held_record_error(tmp_path, target)
    cfg = {"state_root": str(tmp_path / "state")}
    reason = end_turn.unresolved_reason(payload, cfg)
    assert "Repair the record gate" in reason
    assert blocker_state.RECORD_ERROR_KEY in blocker_state.details("s1", "", cfg["state_root"])[0]
