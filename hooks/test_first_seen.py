from __future__ import annotations

from pathlib import Path

import pre_write
import record
import stop
from lib import journal

DASHED = "Old text " + chr(0x2014) + " from before.\n"
NEW_DASH = "New text " + chr(0x2014) + " by the agent.\n"


def _config(tmp_path: Path) -> dict:
    return {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}


def _payload(tmp_path: Path, tool: str, tool_input: dict, call: str) -> dict:
    return {
        "cwd": str(tmp_path / "project"), "session_id": "s1", "tool_name": tool,
        "tool_use_id": call, "tool_input": tool_input,
    }


def _edit(tmp_path: Path, target: Path, old: str, new: str, call: str = "t1") -> tuple[dict, dict]:
    tool_input = {"file_path": str(target), "old_string": old, "new_string": new}
    before = pre_write.run(_payload(tmp_path, "Edit", tool_input, call), _config(tmp_path))
    target.write_text(target.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    after = record.run(_payload(tmp_path, "Edit", tool_input, call), _config(tmp_path))
    return before, after


def _untracked(tmp_path: Path, name: str, body: str) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    target = project / name
    target.write_text(body, encoding="utf-8")
    return target


def _stop(tmp_path: Path) -> dict:
    payload = {"session_id": "s1", "cwd": str(tmp_path / "project"), "hook_event_name": "Stop"}
    return stop.run(payload, _config(tmp_path))


def test_an_edit_of_an_untracked_file_does_not_own_the_old_findings(tmp_path: Path) -> None:
    target = _untracked(tmp_path, "NOTES.md", DASHED + "Plain line.\n")

    _before, after = _edit(tmp_path, target, "Plain line.", "Plain line, edited.")

    assert after.get("decision") != "block"
    assert _stop(tmp_path) == {}


def test_an_edit_of_an_untracked_file_still_blocks_its_new_findings(tmp_path: Path) -> None:
    target = _untracked(tmp_path, "NOTES.md", DASHED + "Plain line.\n")

    _before, after = _edit(tmp_path, target, "Plain line.\n", NEW_DASH)

    assert after["decision"] == "block"
    assert f"{target}:2 " in after["reason"].split("did not write")[0]
    assert f"{target}:1 " not in after["reason"].split("did not write")[0]


def test_a_file_the_agent_wrote_first_gets_no_first_seen_baseline(tmp_path: Path) -> None:
    target = _untracked(tmp_path, "made.md", "")
    record.run(_payload(tmp_path, "Bash", {"command": "printf x > made.md"}, "t0"), _config(tmp_path))
    target.write_text(DASHED + "Plain line.\n", encoding="utf-8")
    record.run(_payload(tmp_path, "Bash", {"command": "printf x > made.md"}, "t1"), _config(tmp_path))

    _before, after = _edit(tmp_path, target, "Plain line.", "Plain line, edited.", "t2")

    assert after["decision"] == "block"
    assert f"{target}:1 " in after["reason"]


def test_the_document_review_sees_only_the_changed_line_of_an_untracked_file(tmp_path: Path) -> None:
    body = "".join(f"line {number}\n" for number in range(1, 21))
    target = _untracked(tmp_path, "NOTES.md", body)

    _edit(tmp_path, target, "line 7\n", "line seven\n")

    rows = journal.read_stop("s1", state_root=_config(tmp_path)["state_root"])
    changed = [number for row in rows if row["role"] == "document" for hunk in row["hunks"] for number in hunk["changed"]]
    assert changed == [7]
