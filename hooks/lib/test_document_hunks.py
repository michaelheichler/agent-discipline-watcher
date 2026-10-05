"""Hunks decide what the reviewer reads, so the edges of a window need their own tests."""
from __future__ import annotations

from lib import document_hunks


def _lines(count: int) -> list[str]:
    return [f"line {number}" for number in range(1, count + 1)]


def _text(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _edited(count: int, *replaced: int) -> tuple[str, str]:
    before = _lines(count)
    after = [f"edited {number}" if number in replaced else line for number, line in enumerate(before, 1)]
    return _text(before), _text(after)


def test_two_adjacent_changed_lines_show_three_context_lines_each_side() -> None:
    hunks = document_hunks.changed_hunks(*_edited(40, 20, 21))

    assert len(hunks) == 1
    assert hunks[0]["start"] == 17
    assert hunks[0]["changed"] == [20, 21]
    assert hunks[0]["lines"] == ["line 17", "line 18", "line 19", "edited 20", "edited 21", "line 22", "line 23", "line 24"]


def test_windows_that_overlap_merge_into_one_hunk() -> None:
    hunks = document_hunks.changed_hunks(*_edited(40, 10, 15))

    assert [(hunk["start"], hunk["changed"]) for hunk in hunks] == [(7, [10, 15])]
    assert len(hunks[0]["lines"]) == 12


def test_distant_changes_stay_separate_hunks() -> None:
    hunks = document_hunks.changed_hunks(*_edited(60, 5, 50))

    assert [hunk["changed"] for hunk in hunks] == [[5], [50]]


def test_a_change_at_the_file_edge_clips_the_window() -> None:
    first, last = document_hunks.changed_hunks(*_edited(30, 1, 30))

    assert first["start"] == 1 and len(first["lines"]) == 4
    assert last["start"] == 27 and last["lines"][-1] == "edited 30"


def test_removed_lines_leave_a_hunk_with_no_changed_line() -> None:
    before = _text(_lines(30))
    after = _text([line for line in _lines(30) if line not in {"line 15", "line 16"}])

    (hunk,) = document_hunks.changed_hunks(before, after)

    assert hunk["changed"] == []
    assert hunk["lines"][:3] == ["line 12", "line 13", "line 14"]
    assert hunk["lines"][3:] == ["line 17", "line 18", "line 19"]
    assert "removed" in document_hunks.hunk_header("a.md", hunk)


def test_identical_text_has_no_hunk() -> None:
    same = _text(_lines(10))

    assert document_hunks.changed_hunks(same, same) == []


def test_an_empty_result_has_no_hunk() -> None:
    assert document_hunks.changed_hunks(_text(_lines(5)), "") == []


def test_an_unknown_base_makes_every_line_changed() -> None:
    (hunk,) = document_hunks.changed_hunks("", _text(_lines(8)))

    assert hunk["changed"] == list(range(1, 9))
    assert hunk["start"] == 1


def test_the_header_names_the_window_and_the_changed_runs() -> None:
    (hunk,) = document_hunks.changed_hunks(*_edited(40, 20, 21, 25))

    assert document_hunks.hunk_header("README.md", hunk) == "README.md lines 17-28, changed lines: 20-21, 25"


def test_only_changed_lines_carry_the_plus_marker() -> None:
    (hunk,) = document_hunks.changed_hunks(*_edited(40, 20))

    rendered = document_hunks.hunk_text("a.md", hunk).split("\n")

    assert rendered[0] == "a.md lines 17-23, changed lines: 20"
    assert [line for line in rendered[1:] if line.startswith("+")] == ["+ edited 20"]
    assert "  line 19" in rendered
