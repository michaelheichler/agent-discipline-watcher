from __future__ import annotations

import pytest

import judge_review
from lib import blocker_state, document_review, end_turn

DOCUMENT = "The cache holds 4096 entries.\n\nIt is important to note that the results were improved.\n"
NOTE = document_review.Note(3, "It is important to note", "Throat clearing.", "State the result.")


def _payload(path, session_id: str) -> dict:
    return {"tool_name": "Write", "session_id": session_id, "tool_input": {"file_path": str(path)}}


def _document(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text(DOCUMENT, encoding="utf-8")
    return target


def _pending(session_id: str) -> dict[str, str]:
    pending, _paths, _revision = blocker_state.details(session_id, "", None)
    return pending


def test_a_document_the_reader_faults_leaves_a_blocker_for_the_stop_hook(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)

    code, message = judge_review.run(_payload(target, "doc-faulted"))

    assert code == judge_review.WAKE_EXIT_CODE
    assert "Throat clearing." in message
    assert any(key.startswith(document_review.BLOCKER_KEY_PREFIX) for key in _pending("doc-faulted"))


def test_a_document_the_reader_clears_leaves_no_blocker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: ())
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)

    judge_review.run(_payload(target, "doc-clean"))

    assert not _pending("doc-clean")


def test_an_unchanged_document_is_not_read_twice(tmp_path, monkeypatch) -> None:
    reads = []
    monkeypatch.setattr(document_review, "review", lambda _path, _text: reads.append(1) or (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)

    judge_review.run(_payload(target, "doc-repeat"))
    judge_review.run(_payload(target, "doc-repeat"))

    assert len(reads) == 1
    assert any(key.startswith(document_review.BLOCKER_KEY_PREFIX) for key in _pending("doc-repeat"))


def test_a_session_scratch_file_costs_no_judge_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(judge_review, "TEMP_ROOTS", (tmp_path,))
    monkeypatch.setattr(document_review, "review", lambda _path, _text: pytest.fail("read a scratch file"))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    scratch = tmp_path / "scratchpad"
    scratch.mkdir()
    target = scratch / "notes.md"
    target.write_text(DOCUMENT, encoding="utf-8")

    assert judge_review.run(_payload(target, "doc-scratch")) == (0, "")


def test_a_document_outside_a_scratchpad_still_reaches_the_reader(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(judge_review, "TEMP_ROOTS", (tmp_path,))
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)

    code, _message = judge_review.run(_payload(target, "doc-not-scratch"))

    assert code == judge_review.WAKE_EXIT_CODE


def test_a_blocker_dies_with_the_file_it_names(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)
    judge_review.run(_payload(target, "doc-deleted"))
    pending, _paths, _revision = blocker_state.details("doc-deleted", "", None)
    target.unlink()
    state = judge_review.session_state.read_state("doc-deleted", None)

    assert end_turn._residual_reasons(pending, [], end_turn._stale_document_keys(pending, state)) == []


def test_a_note_is_dropped_once_the_document_it_quotes_is_rewritten(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)
    judge_review.run(_payload(target, "doc-moved"))
    pending, _paths, _revision = blocker_state.details("doc-moved", "", None)
    target.write_text("A heading was added.\n\n" + DOCUMENT, encoding="utf-8")
    state = judge_review.session_state.read_state("doc-moved", None)

    assert end_turn._residual_reasons(pending, [], end_turn._stale_document_keys(pending, state)) == []


def test_a_note_stands_while_the_document_it_quotes_is_untouched(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)
    judge_review.run(_payload(target, "doc-standing"))
    pending, _paths, _revision = blocker_state.details("doc-standing", "", None)
    state = judge_review.session_state.read_state("doc-standing", None)

    assert end_turn._residual_reasons(pending, [], end_turn._stale_document_keys(pending, state))


def test_a_second_reader_on_the_same_text_finds_the_round_already_spent(tmp_path, monkeypatch) -> None:
    seen = []

    def read(path, text):
        state = judge_review.session_state.read_state("doc-racing", None)
        seen.append(document_review.previous(state, path))
        return (NOTE,)

    monkeypatch.setattr(document_review, "review", read)
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)
    judge_review.run(_payload(target, "doc-racing"))

    assert seen[0][1] == 1


def test_an_empty_reading_still_spends_a_round(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: ())
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)
    judge_review.run(_payload(target, "doc-empty"))
    state = judge_review.session_state.read_state("doc-empty", None)

    assert document_review.previous(state, str(target))[1] == 1


def test_a_document_rewritten_past_the_round_cap_is_handed_back_to_the_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)

    for round_number in range(document_review.MAX_REVIEW_ROUNDS + 1):
        target.write_text(DOCUMENT + f"\nRound {round_number} rewrote this paragraph.\n", encoding="utf-8")
        judge_review.run(_payload(target, "doc-capped"))

    assert not _pending("doc-capped")
