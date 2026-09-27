"""Split out, because pattern rows arrive after the write."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_luna, claude_native, journal, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind

CLOSER = "Feel free to ask me anything else."
PATTERN = {
    "role": "pattern", "rule": "ai_closer", "path": "note.md", "line": 2, "text": CLOSER,
    "content_hash": "abc", "turn_id": "turn-1",
}
VERDICTS = {
    ReviewKind.PATTERN: {"items": [{"index": 0, "verdict": "violating", "reason": "Stock closer."}]},
    ReviewKind.DOCUMENT: {"notes": []},
}
STOP = {"hook_event_name": "Stop", "session_id": "patterns", "stop_hook_active": False}


@pytest.fixture(autouse=True)
def _open_data_boundary(tmp_path: Path) -> None:
    """Opened here, because the gate has its own test file."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"data_boundary": {"enabled": True}}), encoding="utf-8")


class Provider:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        return JudgeResult(
            payload=VERDICTS[request.review_kind], provider="openai-codex", model="gpt-5.6-luna", effort="high",
            rubric_version=request.rubric_version, usage={"input_tokens": 1},
        )


def _journal(tmp_path: Path, rows: list[dict]) -> Path:
    state_root = tmp_path / "state"
    session_state.write_state("patterns", {journal.STATE_KEY: rows, "turn_id": "turn-1"}, state_root)
    return state_root


def _run(tmp_path: Path, state_root: Path, provider: Provider) -> dict:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    return claude_luna.run(
        {**STOP, "cwd": str(tmp_path)}, provider=provider, state_root=state_root,
        settings_path=settings, preset_path=preset,
    )


def test_a_current_turn_pattern_row_becomes_one_pattern_request(tmp_path: Path) -> None:
    work = claude_luna.stop_request(STOP, _journal(tmp_path, [PATTERN]))

    assert work is not None and len(work) == 1
    request, sources = work[0]
    assert request.review_kind is ReviewKind.PATTERN
    assert (request.rule_name, request.candidates) == ("ai_closer", (CLOSER,))
    assert len(request.violating_examples) == len(request.clean_examples) == 4
    assert [row["line"] for row in sources] == [2]


def test_one_request_carries_every_row_of_one_rule(tmp_path: Path) -> None:
    rows = [PATTERN, {**PATTERN, "line": 5, "text": "I hope this helps with your project."}]

    work = claude_luna.stop_request(STOP, _journal(tmp_path, rows))

    assert [len(request.candidates) for request, _rows in work] == [2]


def test_an_unknown_rule_builds_no_request(tmp_path: Path) -> None:
    assert claude_luna.stop_request(STOP, _journal(tmp_path, [{**PATTERN, "rule": "no_such_rule"}])) is None


def test_pattern_and_document_rows_share_the_stop_budget(tmp_path: Path) -> None:
    document = {
        "role": "document", "path": "big.md", "content_hash": "def", "turn_id": "turn-1",
        "source_context": "x" * journal.MAX_STOP_TOTAL_CHARS,
    }

    work = claude_luna.stop_request(STOP, _journal(tmp_path, [PATTERN, document]))

    assert [request.review_kind for request, _rows in work] == [ReviewKind.PATTERN]


def test_a_violating_verdict_blocks_with_a_titled_finding_row(tmp_path: Path) -> None:
    provider = Provider()

    response = _run(tmp_path, _journal(tmp_path, [PATTERN]), provider)

    assert [request.review_kind for request in provider.requests] == [ReviewKind.PATTERN]
    assert response["decision"] == "block"
    assert "ADW Luna pattern review:" in response["reason"]
    assert 'note.md:2 Wrap-up flourish "Feel free to ask me anything else."' in response["reason"]
    assert "(ai_closer)" in response["reason"]


def test_a_judged_pattern_row_is_not_judged_again(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [PATTERN])
    _run(tmp_path, state_root, Provider())
    session_state.update_state("patterns", lambda state: {**state, "turn_id": "turn-2"}, state_root)

    assert claude_luna.stop_request(STOP, state_root) is None
