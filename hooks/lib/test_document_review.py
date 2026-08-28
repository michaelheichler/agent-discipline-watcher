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


def test_an_absent_reviewer_names_nothing(monkeypatch) -> None:
    monkeypatch.setattr(document_review, "available", lambda: False)

    assert document_review.review("a.md", DOCUMENT) == ()


def test_an_empty_document_costs_no_call(monkeypatch) -> None:
    monkeypatch.setattr(document_review, "available", lambda: True)
    monkeypatch.setattr(document_review, "_run", lambda _prompt: pytest.fail("reviewed an empty document"))

    assert document_review.review("a.md", "   \n") == ()


def test_a_rewritten_document_is_remembered_under_its_own_digest() -> None:
    state = document_review.remember({}, "a.md", "abc123", 1)

    assert document_review.previous(state, "a.md") == ("abc123", 1)


def test_a_document_never_reviewed_carries_no_digest_and_no_rounds() -> None:
    assert document_review.previous({}, "a.md") == ("", 0)


def test_two_documents_keep_separate_records() -> None:
    state = document_review.remember(document_review.remember({}, "a.md", "aaa", 1), "b.md", "bbb", 2)

    assert document_review.previous(state, "a.md") == ("aaa", 1)
    assert document_review.previous(state, "b.md") == ("bbb", 2)


def test_the_message_names_the_file_and_the_line() -> None:
    notes = (document_review.Note(3, "quote", "Throat clearing.", "State the result."),)

    assert "a.md:3: Throat clearing. Fix: State the result." in document_review.message("a.md", notes)
