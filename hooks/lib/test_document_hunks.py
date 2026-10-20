"""Hunks decide what the reviewer reads, so the edges of a window need their own tests."""
from __future__ import annotations

import pytest

from lib import document_hunks

DOC = "notes.md"
INTRO = "Intro line here.\n\n"


def _sentences(first: int, last: int) -> list[str]:
    return [f"Sentence {number} of the notes." for number in range(first, last + 1)]


def _lines(count: int) -> list[str]:
    return _sentences(1, count)


def _text(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _edited(count: int, *replaced: int) -> tuple[str, str]:
    before = _lines(count)
    after = [f"Edited sentence {number} here." if number in replaced else line for number, line in enumerate(before, 1)]
    return _text(before), _text(after)


def test_two_adjacent_changed_lines_show_three_context_lines_each_side() -> None:
    hunks = document_hunks.changed_hunks(DOC, *_edited(40, 20, 21))

    assert len(hunks) == 1
    assert hunks[0]["start"] == 17
    assert hunks[0]["changed"] == [20, 21]
    assert hunks[0]["lines"] == [
        *_sentences(17, 19), "Edited sentence 20 here.", "Edited sentence 21 here.", *_sentences(22, 24),
    ]


def test_windows_that_overlap_merge_into_one_hunk() -> None:
    hunks = document_hunks.changed_hunks(DOC, *_edited(40, 10, 15))

    assert [(hunk["start"], hunk["changed"]) for hunk in hunks] == [(7, [10, 15])]
    assert len(hunks[0]["lines"]) == 12


def test_distant_changes_stay_separate_hunks() -> None:
    hunks = document_hunks.changed_hunks(DOC, *_edited(60, 5, 50))

    assert [hunk["changed"] for hunk in hunks] == [[5], [50]]


def test_a_change_at_the_file_edge_clips_the_window() -> None:
    first, last = document_hunks.changed_hunks(DOC, *_edited(30, 1, 30))

    assert first["start"] == 1 and len(first["lines"]) == 4
    assert last["start"] == 27 and last["lines"][-1] == "Edited sentence 30 here."


def test_removed_lines_leave_a_hunk_with_no_changed_line() -> None:
    before = _text(_lines(30))
    after = _text([line for number, line in enumerate(_lines(30), 1) if number not in {15, 16}])

    (hunk,) = document_hunks.changed_hunks(DOC, before, after)

    assert hunk["changed"] == []
    assert hunk["start"] == 12
    assert hunk["lines"] == [*_sentences(12, 14), *_sentences(17, 19)]
    assert "removed" in document_hunks.hunk_header("a.md", hunk)


def test_a_deletion_at_the_top_leaves_a_hunk_from_the_first_line() -> None:
    (hunk,) = document_hunks.changed_hunks(DOC, _text(_lines(30)), _text(_sentences(3, 30)))

    assert (hunk["start"], hunk["changed"]) == (1, [])
    assert hunk["lines"] == _sentences(3, 5)


def test_an_edit_inside_a_wrapped_sentence_marks_every_line_it_covers() -> None:
    before = INTRO + "The hook reads each file\nand checks every rule\nbefore it writes the report.\n"

    (hunk,) = document_hunks.changed_hunks(DOC, before, before.replace("every rule", "each rule"))

    assert hunk["changed"] == [3, 4, 5]


@pytest.mark.parametrize(("path", "before", "after"), [
    pytest.param(
        DOC,
        INTRO + "The hook reads each file and checks every\nrule. It writes the report to the ledger.\n",
        INTRO + "The hook reads each file\nand checks every rule. It writes the\nreport to the ledger.\n",
        id="reflowed-paragraph"),
    pytest.param(
        "src/mod.py",
        "def count():\n    total = 0\n    return total\n",
        "def count():\n  total = 0\n  return total\n",
        id="reindented-code"),
])
def test_a_layout_only_change_has_no_hunk(path: str, before: str, after: str) -> None:
    assert document_hunks.changed_hunks(path, before, after) == []


def test_identical_text_has_no_hunk() -> None:
    same = _text(_lines(10))

    assert document_hunks.changed_hunks(DOC, same, same) == []


def test_an_empty_result_has_no_hunk() -> None:
    assert document_hunks.changed_hunks(DOC, _text(_lines(5)), "") == []


def test_an_unknown_base_makes_every_non_blank_line_changed() -> None:
    (hunk,) = document_hunks.changed_hunks(DOC, "", _text([*_sentences(1, 3), "", *_sentences(4, 6)]))

    assert hunk["changed"] == [1, 2, 3, 5, 6, 7]
    assert hunk["start"] == 1


def test_the_header_names_the_window_and_the_changed_runs() -> None:
    (hunk,) = document_hunks.changed_hunks(DOC, *_edited(40, 20, 21, 25))

    assert document_hunks.hunk_header("README.md", hunk) == "README.md lines 17-28, changed lines: 20-21, 25"


def test_only_changed_lines_carry_the_plus_marker() -> None:
    (hunk,) = document_hunks.changed_hunks(DOC, *_edited(40, 20))

    rendered = document_hunks.hunk_text("a.md", hunk).split("\n")

    assert rendered[0] == "a.md lines 17-23, changed lines: 20"
    assert [line for line in rendered[1:] if line.startswith("+")] == ["+ Edited sentence 20 here."]
    assert "  Sentence 19 of the notes." in rendered
