"""The reader runs on the async route and leaves a blocker behind, because the Stop hook has ten seconds and a whole-document read needs more."""
from __future__ import annotations

import judge_review
from lib import blocker_state, document_review

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


def test_a_document_rewritten_past_the_round_cap_is_handed_back_to_the_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(document_review, "review", lambda _path, _text: (NOTE,))
    monkeypatch.setattr(judge_review.session_state, "_default_root", lambda: tmp_path / "state")
    target = _document(tmp_path)

    for round_number in range(document_review.MAX_REVIEW_ROUNDS + 1):
        target.write_text(DOCUMENT + f"\nRound {round_number} rewrote this paragraph.\n", encoding="utf-8")
        judge_review.run(_payload(target, "doc-capped"))

    assert not _pending("doc-capped")
