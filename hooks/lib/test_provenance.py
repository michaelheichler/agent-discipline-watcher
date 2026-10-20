"""Findings come from the real scanner on the after text, because the gate classifies exactly those rows."""
from __future__ import annotations

from typing import NamedTuple

import pytest

from lib import provenance
from lib.findings import spanning
from lib.prose_structure import sentence_spans
from lib.provenance import block_rules, compare, compare_any
from lib.scanner import scan_all
from lib.test_finding_spans import Case, _every_case

ENGLISH = {"prose_languages": ["en"]}
LONG_FUNCTION = {"function_block_lines": 80}
LONG_LIST = {**ENGLISH, "list_item_cap": 8}
INTRO = "Intro line here.\n\n"
FIVE_WORD_SENTENCES = (
    "The hook reads each file.",
    "The scan checks every rule.",
    "The gate blocks bad writes.",
    "The ledger keeps each row.",
)
FIRST_PARAGRAPH = "The report was written by the team before lunch."
SECOND_PARAGRAPH = "Our second paragraph talks about something else."
THIRD_PARAGRAPH = "A third paragraph closes the short document here."
LONG_SENTENCE = "It is long enough to keep the sentence count right."


class Change(NamedTuple):
    path: str
    before: str
    after: str
    config: dict


def _prose(before: str, after: str) -> Change:
    return Change("doc.md", before, after, ENGLISH)


def _verdicts(change: Change, rule: str) -> list[tuple[int, bool]]:
    result = compare(change.path, change.before, change.after)
    rows = scan_all(change.path, change.after, change.config)
    return [(row["line"], result.owns(row)) for row in rows if row["rule"] == rule]


def _finding(rule: str, line: int) -> dict:
    return {"family": "clean_code", "rule": rule, "line": line, "snippet": ""}


def _paragraphs(*paragraphs: str) -> str:
    return "\n\n".join(paragraphs) + "\n"


def _variance_paragraph(*sentences: str) -> str:
    return INTRO + "\n".join(sentences) + "\n"


def _endings_document() -> str:
    paragraphs = (
        f"{LONG_SENTENCE}\nMiddle number {index} sits here quietly.\nIt {verb}.\n"
        for index, verb in enumerate(("stops", "waits", "ends"))
    )
    return "\n".join(paragraphs)


def _counter_function(indent: str = "    ", comment: str = "increments the counter") -> str:
    return f"def count():\n{indent}total = 0\n{indent}# {comment}\n{indent}total += 1\n{indent}return total\n"


def _long_function(*extra: str) -> str:
    body = "".join(f"    v{number} = {number}\n" for number in range(90))
    return "import os\n\ndef big():\n" + body + "".join(extra) + "    return v0\n"


def _long_list(count: int) -> str:
    return INTRO + "".join(f"- Item number {number} goes here\n" for number in range(count))


def _merge_function(*comments: str) -> str:
    steps = {"increments the counter": "total += 1", "resets the counter": "total = 0", "decrements the total": "total -= 1"}
    body = "".join(f"    # {comment}\n    {steps[comment]}\n" for comment in comments)
    return "def count():\n    total = 0\n" + body + "    return total\n"


def _repetitive_code() -> list[str]:
    blocks = (
        (f"function handler{index}(event) {{", "  const value = event.payload;", "  log(value);", "  return value;", "}")
        for index in range(5000)
    )
    return [line for block in blocks for line in block]


def _edited(lines: list[str], every: int) -> list[str]:
    return [f"  edited{number}();" if number % every == 0 else line for number, line in enumerate(lines)]


def _joined(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("change", [
    pytest.param(_prose(*[INTRO + "The report was written by the team.\nWe utilize the tool.\n"] * 2), id="prose"),
    pytest.param(Change("src/mod.py", _counter_function(), _counter_function(), {}), id="code"),
])
def test_an_unchanged_file_leaves_every_finding_inherited(change: Change) -> None:
    rows = scan_all(change.path, change.after, change.config)
    result = compare(change.path, change.before, change.after)

    assert rows
    assert [row for row in rows if result.owns(row)] == []


@pytest.mark.parametrize(("change", "rule", "expected"), [
    pytest.param(
        _prose(
            INTRO + "The report was written by the team before\nthe meeting began today.\n",
            INTRO + "The report was written\nby the team before the meeting began today.\n"),
        "passive_voice", [(3, False)], id="reflowed-paragraph-keeps-its-passive"),
    pytest.param(
        _prose(INTRO + "The report was written by the team.\n", INTRO + "The plan was drafted by the team.\n"),
        "passive_voice", [(3, True)], id="new-passive-replacing-an-old-one"),
    pytest.param(
        _prose("# Utilize the heading\n\nBody text here is fine.\n", "# Utilize the new heading\n\nBody text here is fine.\n"),
        "utilize", [(1, True)], id="edited-heading"),
    pytest.param(
        _prose("Intro.\n\n- An item was written by the team\n- Other item\n",
               "Intro.\n\n- An item was written by the board\n- Other item\n"),
        "passive_voice", [(3, True)], id="edited-list-item"),
])
def test_a_prose_finding_is_owned_only_when_its_words_changed(change: Change, rule: str, expected: list) -> None:
    assert _verdicts(change, rule) == expected


@pytest.mark.parametrize(("change", "expected"), [
    pytest.param(
        _prose(
            INTRO + "The report was written by the team. The plan got drafted today.\n",
            INTRO + "The report was written by the team. The plan got approved today.\n"),
        [(3, False)], id="match-in-the-unchanged-sentence"),
    pytest.param(
        _prose(
            INTRO + "The plan was drafted by the board. The report goes to the team.\n",
            INTRO + "The plan was approved by the board. The report goes to the team.\n"),
        [(3, True)], id="match-in-the-changed-sentence"),
])
def test_a_shared_line_judges_a_match_by_the_sentence_that_holds_it(change: Change, expected: list) -> None:
    assert _verdicts(change, "passive_voice") == expected


def test_an_edit_to_a_later_sentence_of_a_low_variance_paragraph_owns_the_finding() -> None:
    before = _variance_paragraph(*FIVE_WORD_SENTENCES)
    change = _prose(before, before.replace("The gate blocks bad writes.", "The gate stops bad writes."))

    assert _verdicts(change, "low_sentence_variance") == [(3, True)]


@pytest.mark.parametrize(("after", "expected"), [
    pytest.param(_paragraphs(SECOND_PARAGRAPH, THIRD_PARAGRAPH, FIRST_PARAGRAPH), [(5, False)], id="moved-paragraph"),
    pytest.param(
        _paragraphs(FIRST_PARAGRAPH, SECOND_PARAGRAPH, THIRD_PARAGRAPH, FIRST_PARAGRAPH),
        [(1, False), (7, True)], id="extra-copy"),
])
def test_a_moved_paragraph_stays_inherited_and_an_extra_copy_is_owned(after: str, expected: list) -> None:
    before = _paragraphs(FIRST_PARAGRAPH, SECOND_PARAGRAPH, THIRD_PARAGRAPH)

    assert _verdicts(_prose(before, after), "passive_voice") == expected


@pytest.mark.parametrize(("old", "new", "expected"), [
    pytest.param("Middle number 1 sits", "Middle number one sits", [(1, False)], id="mid-paragraph-sentence"),
    pytest.param("It waits.", "It pauses.", [(1, True)], id="paragraph-ending-sentence"),
])
def test_uniform_endings_follow_only_the_paragraph_ending_sentences(old: str, new: str, expected: list) -> None:
    before = _endings_document()

    assert _verdicts(_prose(before, before.replace(old, new)), "uniform_paragraph_endings") == expected


@pytest.mark.parametrize(("after", "expected"), [
    pytest.param(_counter_function(indent="  "), [(3, False)], id="reindented-block"),
    pytest.param(_counter_function(comment="increments the total"), [(3, True)], id="reworded-comment"),
    pytest.param(
        "def count():\n    total = 0\n    total += 1\n    # increments the counter\n    return total\n",
        [(4, False)], id="moved-comment-line"),
])
def test_a_code_comment_is_owned_only_when_its_line_text_changed(after: str, expected: list) -> None:
    assert _verdicts(Change("src/mod.py", _counter_function(), after, {}), "what_comment") == expected


@pytest.mark.parametrize(("moved", "expected"), [
    pytest.param("}", True, id="short-closing-brace"),
    pytest.param("  cleanupResources(handle);", False, id="long-statement"),
])
def test_only_a_line_long_enough_to_prove_a_move_counts_as_moved(moved: str, expected: bool) -> None:
    before = f"first_call_here();\n{moved}\nsecond_call_here();\n}}\nthird_call_here();\n"
    after = f"first_call_here();\nsecond_call_here();\n}}\nthird_call_here();\n{moved}\n"

    assert compare("src/app.js", before, after).owns(_finding("what_comment", 5)) is expected


def test_a_lone_brace_cannot_displace_a_longer_moved_line() -> None:
    result = compare("src/app.js", "start();\n}\nfinishAllPendingWork();\n", "start();\nfinishAllPendingWork();\n}\n")

    assert [result.owns(_finding("what_comment", line)) for line in (2, 3)] == [False, True]


@pytest.mark.parametrize(("after", "expected"), [
    pytest.param(_long_function().replace("    v5 = 5\n", "    v5 = 55\n"), [(3, False)], id="one-line-edit"),
    pytest.param(_long_function("    extra = 1\n"), [(3, True)], id="grown-by-one-line"),
])
def test_a_long_function_is_owned_only_when_it_grew(after: str, expected: list) -> None:
    change = Change("src/mod.py", _long_function(), after, LONG_FUNCTION)

    assert _verdicts(change, "function_too_long") == expected


@pytest.mark.parametrize(("before", "expected"), [
    pytest.param(
        _variance_paragraph(*FIVE_WORD_SENTENCES[:2], "An extra sentence sat here.", *FIVE_WORD_SENTENCES[2:]),
        [(3, True)], id="sentence-deleted-inside-the-span"),
    pytest.param(
        _variance_paragraph(*FIVE_WORD_SENTENCES, "An extra sentence sat here."),
        [(3, True)], id="sentence-deleted-after-the-last-line"),
    pytest.param(
        INTRO + "An extra paragraph sat here.\n\n" + "\n".join(FIVE_WORD_SENTENCES) + "\n",
        [(3, False)], id="paragraph-deleted-before-the-span"),
])
def test_a_deletion_owns_a_block_finding_only_when_it_falls_within_the_span(before: str, expected: list) -> None:
    change = _prose(before, _variance_paragraph(*FIVE_WORD_SENTENCES))

    assert _verdicts(change, "low_sentence_variance") == expected


def test_a_one_line_prose_finding_ignores_a_deletion_right_after_it() -> None:
    after = INTRO + "The report was written by the team.\n"

    assert _verdicts(_prose(after + "Another sentence follows here.\n", after), "passive_voice") == [(3, False)]


@pytest.mark.parametrize(("change", "rule"), [
    pytest.param(
        Change("src/mod.py", _long_function(), _long_function().replace("    v5 = 5\n", ""), LONG_FUNCTION),
        "function_too_long", id="function_too_long"),
    pytest.param(Change("doc.md", _long_list(11), _long_list(10), LONG_LIST), "oversized_list", id="oversized_list"),
])
def test_a_size_finding_stays_inherited_when_a_deletion_shrinks_its_span(change: Change, rule: str) -> None:
    assert _verdicts(change, rule) == [(3, False)]


@pytest.mark.parametrize(("after", "expected"), [
    pytest.param("b = 2\n\nc = 3\n\nd = 4\n", frozenset({0}), id="top-of-file"),
    pytest.param("a = 1\n\nb = 2\n\nd = 4\n", frozenset({3}), id="middle"),
    pytest.param("a = 1\n\nb = 2\n\nc = 3\n", frozenset({5}), id="end-of-file"),
])
def test_a_removal_seam_names_the_line_the_deletion_follows(after: str, expected: frozenset[int]) -> None:
    assert compare("src/mod.py", "a = 1\n\nb = 2\n\nc = 3\n\nd = 4\n", after).removed_seams == expected


def test_a_merge_inherits_lines_from_either_parent_and_owns_lines_from_neither() -> None:
    after = _merge_function("increments the counter", "resets the counter", "decrements the total")
    parents = [_merge_function("increments the counter"), _merge_function("resets the counter")]
    result = compare_any("src/mod.py", parents, after)

    verdicts = [(row["line"], result.owns(row)) for row in scan_all("src/mod.py", after, {})]

    assert verdicts == [(3, False), (5, False), (7, True)]


def test_no_parent_owns_every_finding() -> None:
    after = _counter_function()
    result = compare_any("src/mod.py", [], after)

    assert [(row["line"], result.owns(row)) for row in scan_all("src/mod.py", after, {})] == [(3, True)]


def test_a_two_percent_edit_of_repetitive_code_marks_about_two_percent_changed() -> None:
    before = _repetitive_code()

    changed = compare("src/app.js", _joined(before), _joined(_edited(before, 50))).changed_lines

    assert 0.015 * len(before) <= len(changed) <= 0.03 * len(before)


def test_no_time_left_marks_the_whole_middle_changed() -> None:
    before = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"
    after = "a = 1\nb = 20\nc = 3\nd = 40\ne = 5\n"

    assert compare("src/mod.py", before, after, check=lambda: 0).changed_lines == frozenset({2, 3, 4})


def test_a_gap_over_the_cell_cap_counts_as_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provenance, "MAX_DIFF_CELLS", 0)

    result = compare("src/app.js", "}\n}\nold_tail();\n", "new_head();\n}\n}\n")

    assert result.changed_lines == frozenset({1, 2, 3})


def test_spanning_rejects_a_rule_not_declared_as_a_block_rule() -> None:
    with pytest.raises(ValueError):
        spanning(scan_all("src/mod.py", _counter_function(), {})[0], 5)


@pytest.mark.parametrize("case", [pytest.param(case, id=name) for name, case in _every_case().items()])
def test_every_rule_that_emits_an_end_line_is_a_block_rule(case: Case) -> None:
    rows = scan_all(case.path, case.text, case.config)

    assert {row["rule"] for row in rows if row.get("end_line") is not None} - block_rules() == set()


@pytest.mark.parametrize(("paragraph", "expected"), [
    pytest.param([(3, "One sentence only.")], [(3, "One sentence only.")], id="single"),
    pytest.param(
        [(1, "First one. Second one! Third one? fourth stays lowercase.")],
        [(1, "First one."), (1, "Second one!"), (1, "Third one? fourth stays lowercase.")], id="one-line"),
    pytest.param(
        [(4, "A sentence that wraps"), (5, "across two lines. Then another"), (6, "one ends here.")],
        [(4, "A sentence that wraps across two lines."), (5, "Then another one ends here.")], id="wrapped"),
    pytest.param(
        [(2, "Version 2.0 shipped. It works."), (3, "See e.g. The docs.")],
        [(2, "Version 2.0 shipped."), (2, "It works."), (3, "See e.g."), (3, "The docs.")], id="abbreviations"),
    pytest.param(
        [(7, "No terminal punctuation"), (8, "at all")], [(7, "No terminal punctuation at all")], id="unterminated"),
    pytest.param(
        [(1, "Ends with a break.  "), (2, "Next line starts.")],
        [(1, "Ends with a break."), (2, "Next line starts.")], id="trailing-spaces"),
    pytest.param(
        [(1, "Quote ends.\" Then more."), (2, "Done.")], [(1, "Quote ends.\" Then more."), (2, "Done.")], id="quote"),
    pytest.param([(9, "Trailing period."), (10, "")], [(9, "Trailing period. ")], id="empty-last-line"),
    pytest.param(
        [(1, "Line ends with a period."), (2, "Next starts upper."), (3, "lower next.")],
        [(1, "Line ends with a period."), (2, "Next starts upper. lower next.")], id="lowercase-continuation"),
])
def test_sentence_spans_split_like_the_released_splitter(paragraph: list, expected: list) -> None:
    assert [(span.first, span.text) for span in sentence_spans(paragraph)] == expected


@pytest.mark.parametrize(("number", "expected"), [
    pytest.param(12, frozenset(), id="a-later-number-continues-the-paragraph"),
    pytest.param(1, frozenset({3, 4}), id="one-starts-a-list"),
])
def test_a_reflow_that_puts_a_number_at_a_line_start_counts_only_when_it_starts_a_list(
    number: int, expected: frozenset[int],
) -> None:
    before = INTRO + f"The upgrade moved everyone to version {number}. The old servers went offline.\n"
    after = INTRO + f"The upgrade moved everyone to version\n{number}. The old servers went offline.\n"

    assert compare("doc.md", before, after).changed_lines == expected


def test_a_one_line_edit_in_a_block_of_bare_lines_marks_only_that_line() -> None:
    roster = [f"Entry {number} in the roster" for number in range(1, 41)]
    edited = [*roster[:19], "Entry twenty in the roster", *roster[20:]]

    assert compare("doc.md", _joined(roster), _joined(edited)).changed_lines == frozenset({20})


def test_a_one_word_edit_in_a_long_wrapped_sentence_marks_the_whole_sentence() -> None:
    sentence = (
        "The hook reads the file\nand checks every rule\nagainst the stored config\n"
        "before it writes the report\nto the ledger on disk.\n"
    )

    result = compare("doc.md", INTRO + sentence, INTRO + sentence.replace("stored", "merged"))

    assert result.changed_lines == frozenset({3, 4, 5, 6, 7})


def test_an_edit_to_a_numbered_item_leaves_the_wrapped_item_before_it_unchanged() -> None:
    steps = "Steps:\n\n1. Install the hook into the\n   repository root.\n2. Restart the shell so the\n   hook loads.\n"

    assert compare("doc.md", steps, steps.replace("Restart", "Reload")).changed_lines == frozenset({5})
