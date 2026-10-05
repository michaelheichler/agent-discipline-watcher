"""The base of a turn decides which lines count as changed, so each source has its own test."""
from __future__ import annotations

from pathlib import Path

from lib import journal
from testing import make_repo, run_git


def _body(*replaced: int) -> str:
    return "".join(f"edited {n}\n" if n in replaced else f"line {n}\n" for n in range(1, 41))


def _document(state_root: Path) -> dict:
    return next(row for row in journal.read("s", state_root=state_root) if row["role"] == "document")


def _changed(state_root: Path) -> list[int]:
    return [number for hunk in journal.read_stop("s", turn_id="t2", state_root=state_root)[0]["hunks"] for number in hunk["changed"]]


def test_two_writes_in_one_turn_share_the_content_from_before_the_first(tmp_path: Path) -> None:
    doc, state = tmp_path / "a.md", tmp_path / "state"
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t1", "u0", doc, state_root=state)
    doc.write_text(_body(5), encoding="utf-8")
    journal.record_edit("s", "t2", "u1", doc, state_root=state)
    doc.write_text(_body(5, 30), encoding="utf-8")
    journal.record_edit("s", "t2", "u2", doc, state_root=state)

    assert _document(state)["before_context"] == _body()
    assert _changed(state) == [5, 30]


def test_a_later_turn_starts_from_the_text_the_last_turn_left(tmp_path: Path) -> None:
    doc, state = tmp_path / "a.md", tmp_path / "state"
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t1", "u1", doc, state_root=state)
    doc.write_text(_body(5), encoding="utf-8")
    journal.record_edit("s", "t1", "u2", doc, state_root=state)
    doc.write_text(_body(5, 30), encoding="utf-8")
    journal.record_edit("s", "t2", "u3", doc, state_root=state)

    assert _document(state)["before_context"] == _body(5)
    assert _changed(state) == [30]


def test_the_first_edit_of_a_session_diffs_against_the_committed_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    doc = repo / "README.md"
    doc.write_text(_body(), encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-q", "-m", "seed")
    doc.write_text(_body(7, 8), encoding="utf-8")
    journal.record_edit("s", "t2", "u1", doc, state_root=tmp_path / "state")

    assert _changed(tmp_path / "state") == [7, 8]


def test_a_file_with_no_known_base_counts_as_new(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t2", "u1", doc, state_root=tmp_path / "state")

    assert _document(tmp_path / "state")["before_context"] is None
    assert _changed(tmp_path / "state") == list(range(1, 41))


def test_a_code_file_row_keeps_no_base(tmp_path: Path) -> None:
    code = tmp_path / "a.py"
    code.write_text("value = 1\n", encoding="utf-8")

    journal.record_edit("s", "t1", "u1", code, state_root=tmp_path / "state")

    assert all("before_context" not in row for row in journal.read("s", state_root=tmp_path / "state"))


def test_the_row_keeps_the_whole_text_for_the_hosts_that_read_it(tmp_path: Path) -> None:
    doc, state = tmp_path / "a.md", tmp_path / "state"
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t1", "u1", doc, state_root=state)
    doc.write_text(_body(5), encoding="utf-8")
    journal.record_edit("s", "t2", "u2", doc, state_root=state)

    assert _document(state)["source_context"] == _body(5)


def test_an_edit_the_agent_reverted_has_nothing_to_review(tmp_path: Path) -> None:
    doc, state = tmp_path / "a.md", tmp_path / "state"
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t1", "u1", doc, state_root=state)
    journal.mark_reviewed("s", journal.read_stop("s", turn_id="t1", state_root=state), state_root=state)
    doc.write_text(_body(5), encoding="utf-8")
    journal.record_edit("s", "t2", "u2", doc, state_root=state)
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t2", "u3", doc, state_root=state)

    assert journal.read_stop("s", turn_id="t2", state_root=state) == []


def test_a_turn_that_leaves_the_text_unchanged_has_nothing_to_review(tmp_path: Path) -> None:
    doc, state = tmp_path / "a.md", tmp_path / "state"
    doc.write_text(_body(), encoding="utf-8")
    journal.record_edit("s", "t1", "u1", doc, state_root=state)
    journal.mark_reviewed("s", journal.read_stop("s", turn_id="t1", state_root=state), state_root=state)
    journal.record_edit("s", "t2", "u2", doc, state_root=state)

    assert journal.read_stop("s", turn_id="t2", state_root=state) == []
