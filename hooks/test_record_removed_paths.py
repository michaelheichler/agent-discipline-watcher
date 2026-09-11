from pathlib import Path

import pytest

import record
import stop
from lib import journal, reporting


@pytest.fixture(autouse=True)
def isolated_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reporting, "_reports_dir", lambda: tmp_path / "reports")


def _payload(tmp_path: Path, patch: str) -> tuple[dict, dict]:
    return {
        "session_id": "removed", "cwd": str(tmp_path), "tool_name": "apply_patch",
        "turn_id": "host-turn", "tool_use_id": "patch", "tool_input": {"input": patch},
    }, {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}


def test_successful_delete_is_journalled_without_an_unscannable_finding(tmp_path: Path) -> None:
    source = tmp_path / "removed.md"
    source.write_text("The archive contains seven records.\n", encoding="utf-8")
    payload, config = _payload(tmp_path, "*** Begin Patch\n*** Delete File: removed.md\n*** End Patch\n")
    journal.record_edit("removed", "host-turn", "before", source, state_root=config["state_root"])
    source.unlink()

    assert record.run(payload, config) == {}
    assert journal.read("removed", state_root=config["state_root"]) == []
    assert stop.run(payload, config) == {}


@pytest.mark.parametrize("lines", [1, 1000])
def test_successful_move_scans_only_the_remaining_destination(tmp_path: Path, lines: int) -> None:
    (tmp_path / "moved.py").write_text("value = 1\n" * lines, encoding="utf-8")
    patch = "*** Begin Patch\n*** Update File: original.py\n*** Move to: moved.py\n@@\n-value = 0\n+value = 1\n*** End Patch\n"
    payload, config = _payload(tmp_path, patch)

    response = record.run(payload, config)

    assert "unscannable_file" not in response.get("reason", "")
    assert (response.get("decision") == "block") == (lines >= 1000)
    if lines >= 1000:
        assert "file_too_long" in response["reason"]


@pytest.mark.parametrize("operation", ["Add", "Update"])
def test_missing_write_targets_still_block(tmp_path: Path, operation: str) -> None:
    payload, config = _payload(tmp_path, f"*** Begin Patch\n*** {operation} File: missing.py\n+value = 1\n*** End Patch\n")

    response = record.run(payload, config)

    assert response["decision"] == "block"
    assert "unscannable_file" in response["reason"]
    assert "missing.py:1" in response["reason"]


def test_unfinished_delete_still_scans_existing_content(tmp_path: Path) -> None:
    (tmp_path / "remaining.py").write_text("value = 1\n" * 1000, encoding="utf-8")
    payload, config = _payload(tmp_path, "*** Begin Patch\n*** Delete File: remaining.py\n*** End Patch\n")

    response = record.run(payload, config)

    assert response["decision"] == "block"
    assert "file_too_long" in response["reason"]
