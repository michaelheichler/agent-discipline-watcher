"""Split out because pattern rows arrive after the write."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import stop
from lib import journal, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind

CLOSER = "Feel free to ask me anything else."
DOCUMENT = {"role": "document", "path": "note.md", "source_context": "A sentence.", "turn_id": "turn-1"}
COMMENT = {"role": "comment", "path": "code.py", "line": 4, "text": "Returns rows.", "turn_id": "turn-1"}
PATTERN = {"role": "pattern", "rule": "ai_closer", "path": "note.md", "line": 2, "text": CLOSER, "turn_id": "turn-1"}


@pytest.fixture(autouse=True)
def _open_data_boundary(tmp_path: Path) -> None:
    """Opened here, because the gate has its own test file."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"data_boundary": {"enabled": True}}), encoding="utf-8")


VERDICTS = {
    ReviewKind.COMMENT: {"items": [{"index": 0, "verdict": "states_why", "reason": "Names a constraint."}]},
    ReviewKind.PATTERN: {"items": [{"index": 0, "verdict": "violating", "reason": "Stock closer."}]},
    ReviewKind.DOCUMENT: {"notes": []},
}


def _provider() -> SimpleNamespace:
    calls: list[JudgeRequest] = []

    def judge(request: JudgeRequest) -> JudgeResult:
        calls.append(request)
        return JudgeResult(
            payload=VERDICTS[request.review_kind], provider="openai-codex", model="gpt-5.6-luna", effort="high",
            rubric_version="adw-rubric-v1", usage={"total_tokens": 1},
        )

    return SimpleNamespace(calls=calls, judge=judge)


def _review(tmp_path: Path, rows: list[dict]) -> tuple[dict, SimpleNamespace]:
    session_state.write_state("patterns", {journal.STATE_KEY: rows}, tmp_path / "state")
    provider = _provider()
    response = stop.run(
        {"session_id": "patterns", "turn_id": "turn-1", "stop_hook_active": False, "cwd": str(tmp_path)},
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
        provider=provider,
    )
    return response, provider


def test_codex_judges_pattern_rows_beside_documents_and_comments(tmp_path) -> None:
    response, provider = _review(tmp_path, [DOCUMENT, COMMENT, PATTERN])

    assert [request.review_kind for request in provider.calls] == [
        ReviewKind.DOCUMENT, ReviewKind.COMMENT, ReviewKind.PATTERN,
    ]
    pattern = provider.calls[-1]
    assert (pattern.rule_name, pattern.candidates) == ("ai_closer", (CLOSER,))
    assert len(pattern.violating_examples) == len(pattern.clean_examples) == 4
    assert response["decision"] == "block"
    assert "ADW Luna pattern review" in response["reason"]
    assert "note.md:2" in response["reason"]


def test_one_request_carries_every_row_of_one_rule(tmp_path) -> None:
    rows = [PATTERN, {**PATTERN, "line": 5, "text": "I hope this helps with your project."}]

    _response, provider = _review(tmp_path, rows)

    assert [len(request.candidates) for request in provider.calls] == [2]


def test_pattern_rows_from_another_turn_are_not_judged(tmp_path) -> None:
    response, provider = _review(tmp_path, [{**PATTERN, "turn_id": "turn-0"}])

    assert provider.calls == []
    assert response == {}


def test_an_incomplete_pattern_row_fails_closed(tmp_path) -> None:
    response, provider = _review(tmp_path, [{**PATTERN, "rule": ""}])

    assert provider.calls == []
    assert "incomplete pattern candidate" in response["reason"]
