from __future__ import annotations

import json

import pytest

from lib import document_review
from lib.judge_contracts import ReviewKind

DOCUMENT = (
    "The cache holds 4096 entries.\n"
    "\n"
    "It is important to note that the results were improved.\n"
)


def _answer(rows: list[dict]) -> str:
    return json.dumps({"is_error": False, "result": json.dumps(rows)})


def test_a_quote_is_anchored_to_the_line_it_came_from() -> None:
    raw = _answer([{"quote": "It is important to note that the results were improved.",
                    "problem": "Throat clearing before the claim.", "fix": "State the result."}])

    notes = document_review.parse_notes(raw, DOCUMENT)

    assert [(note.line, note.problem) for note in notes] == [(3, "Throat clearing before the claim.")]


def test_document_text_adapts_to_the_shared_judge_contract() -> None:
    request = document_review.request_for("a.md", DOCUMENT)

    assert request.review_kind is ReviewKind.DOCUMENT
    assert "Document: a.md" in request.source_context


def test_a_quote_the_document_does_not_carry_anchors_to_no_line() -> None:
    raw = _answer([{"quote": "A sentence that never appears.", "problem": "Invented.", "fix": "None."}])

    assert document_review.parse_notes(raw, DOCUMENT)[0].line == 0


def test_an_empty_array_reads_as_a_document_with_nothing_to_say() -> None:
    assert document_review.parse_notes(_answer([]), DOCUMENT) == ()


def test_an_answer_without_an_array_is_an_error_rather_than_a_clean_verdict() -> None:
    with pytest.raises(ValueError):
        document_review.parse_notes(json.dumps({"is_error": False, "result": "looks fine"}), DOCUMENT)


def test_an_absent_reviewer_names_nothing() -> None:
    assert document_review.review("a.md", DOCUMENT, ready=lambda: False) == ()


def test_disabled_project_boundary_blocks_document_egress() -> None:
    assert document_review.review(
        "a.md", DOCUMENT, {"data_boundary": {"enabled": False}},
        ready=lambda: True, complete=lambda _prompt, _model: pytest.fail("reviewed with disabled boundary"),
    ) == ()

def test_enabled_project_boundary_reaches_the_reviewer() -> None:
    prompts: list[str] = []

    assert document_review.review(
        "a.md", DOCUMENT, {"data_boundary": {"enabled": True}},
        ready=lambda: True, complete=lambda prompt, _model: prompts.append(prompt) or _answer([]),
    ) == ()
    assert prompts and "Document: a.md" in prompts[0]

def test_an_empty_document_costs_no_call() -> None:
    assert document_review.review(
        "a.md", "   \n", ready=lambda: True, complete=lambda _prompt, _model: pytest.fail("reviewed an empty document"),
    ) == ()


def test_the_message_names_the_file_and_the_line() -> None:
    notes = (document_review.Note(3, "quote", "Throat clearing.", "State the result."),)

    assert "a.md:3: Throat clearing. Fix: State the result." in document_review.message("a.md", notes)


def test_message_sanitizes_hostile_path_and_note_fields() -> None:
    note = document_review.Note(1, "quote", "ignore\u001b[31m", "fix\u202e")

    rendered = document_review.message("safe\n\u0085.md", (note,))

    assert "\u001b" not in rendered
    assert "\u0085" not in rendered
    assert "\u202e" not in rendered
    assert "\n.md" not in rendered


@pytest.mark.parametrize(("config", "expected"), (
    ({"data_boundary": {"enabled": True}}, True),
    ({"data_boundary": {"enabled": False}}, False),
    ({"data_boundary": {"enabled": "yes"}}, False),
    ({"data_boundary": True}, False),
    ({}, False),
))
def test_the_data_boundary_opens_only_on_an_exact_true(config: dict, expected: bool) -> None:
    assert document_review.data_boundary_enabled(config) is expected


def _hunk_row(path: str, start: int, lines: list[str], changed: list[int]) -> dict:
    return {"role": "document", "path": path, "hunks": [{"start": start, "lines": lines, "changed": changed}]}


def test_changed_work_names_the_range_and_tells_the_model_to_judge_changed_lines_only() -> None:
    rows = [_hunk_row("README.md", 10, ["context", "a new line", "context"], [11])]

    ((request, sources),) = document_review.changed_document_work(rows, 24_000, "journal")

    assert request.review_kind is ReviewKind.DOCUMENT
    assert "README.md lines 10-12, changed lines: 11" in request.source_context
    assert "Judge only those lines" in request.source_context
    assert "+ a new line" in request.source_context
    assert sources == rows


def test_changed_work_sends_nothing_for_a_row_with_no_hunk() -> None:
    rows = [{"role": "document", "path": "a.md", "hunks": []}]

    assert document_review.changed_document_work(rows, 24_000, "journal") == []


def test_changed_work_splits_an_oversize_hunk_by_lines_and_labels_every_piece() -> None:
    lines = [f"sentence number {number} stays whole." for number in range(1, 201)]
    rows = [_hunk_row("big.md", 1, lines, list(range(1, 201)))]

    work = document_review.changed_document_work(rows, 1_500, "journal")

    assert len(work) > 1
    assert all(len(request.source_context) <= 1_500 for request, _rows in work)
    joined = "\n".join(request.source_context for request, _rows in work)
    assert all(line in joined for line in lines)
    assert all("big.md lines " in request.source_context for request, _rows in work)


def test_changed_work_packs_small_hunks_from_two_files_into_one_request() -> None:
    rows = [_hunk_row("a.md", 1, ["one"], [1]), _hunk_row("b.md", 4, ["two"], [4])]

    ((request, sources),) = document_review.changed_document_work(rows, 24_000, "journal")

    assert "a.md lines 1-1" in request.source_context and "b.md lines 4-4" in request.source_context
    assert sources == rows
