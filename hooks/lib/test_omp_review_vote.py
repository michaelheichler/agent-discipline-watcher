"""Split out because OMP has no async route to vote on."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import embedding_session, journal, omp_review, pattern_vote
from lib.pattern_judge import PatternCandidate

CLOSER = "Feel free to ask me anything else."
WARM_URL = "http://127.0.0.1:1/v1/embeddings"
WARM = pattern_vote.Voter(
    open_turn=lambda *_args: WARM_URL,
    renew_turn=lambda *_args: True,
    candidates=lambda path, _text, _config: {"inflated_diction": (PatternCandidate(path, 1, CLOSER),)},
)


@pytest.fixture(name="document")
def _document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")
    path = tmp_path / "notes.md"
    path.write_text(f"{CLOSER}\n", encoding="utf-8")
    return path


def _config(path: Path) -> dict:
    return {"data_boundary": {"enabled": True}, "state_root": str(path.parent / "state")}


def _request(path: Path, operation: str, voter: pattern_vote.Voter = WARM, **fields: object) -> dict:
    payload = {"cwd": str(path.parent), "session_id": "omp-vote", "tool_input": {"file_path": str(path)}}
    return omp_review.run({"operation": operation, "payload": payload, **fields}, _config(path), voter=voter)


def _pattern_requests(prepared: dict) -> list[dict]:
    return [request for request in prepared["requests"] if request["kind"] == "pattern"]


def test_prepare_journals_the_vote_before_it_builds_pattern_work(document: Path) -> None:
    [request] = _pattern_requests(_request(document, "prepare"))

    assert CLOSER in request["prompt"]
    assert request["candidate_count"] == 1


def test_validate_reuses_the_journal_without_voting_again(document: Path) -> None:
    prepared = _request(document, "prepare")
    [request] = _pattern_requests(prepared)
    no_second_vote = WARM._replace(candidates=lambda *_args: pytest.fail("voted twice"))
    output = json.dumps({"items": [{"index": 0, "verdict": "violating", "reason": "Stock closer."}]})

    result = _request(
        document, "validate", no_second_vote, digest=prepared["digest"], request_id=request["id"], output=output,
    )

    assert result["decision"] == "block"
    assert "Stock closer." in result["reason"]


def test_a_journal_change_after_prepare_invalidates_the_digest(document: Path) -> None:
    prepared = _request(document, "prepare")
    source = journal.current_source(document)
    assert source is not None
    journal.record_patterns(
        "omp-vote", "turn", document, [{"rule": "utilize", "line": 1, "text": CLOSER}],
        content_hash=source[0], state_root=document.parent / "state",
    )

    with pytest.raises(ValueError, match="changed"):
        _request(document, "validate", digest=prepared["digest"], request_id=0, output="{}")


def test_a_cold_model_leaves_prepare_without_pattern_work(document: Path, monkeypatch) -> None:
    cold = WARM._replace(open_turn=lambda *_args: None, probe=lambda: None)
    monkeypatch.setattr(omp_review, "VOTE_READY_SECONDS", 0.0)

    assert _pattern_requests(_request(document, "prepare", cold)) == []
