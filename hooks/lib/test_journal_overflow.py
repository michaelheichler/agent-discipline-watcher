from __future__ import annotations

from pathlib import Path

import pytest

import stop
from lib import codex_luna, journal, session_state
from lib.judge import Candidate
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind


class Provider:
    def __init__(self) -> None:
        self.calls: list[JudgeRequest] = []

    @property
    def request_count(self) -> int:
        return len(self.calls)

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.calls.append(request)
        payload = (
            {"items": [
                {"index": index, "verdict": "states_why", "reason": "Names the reason."}
                for index in range(len(request.candidates))
            ]}
            if request.review_kind is ReviewKind.COMMENT else {"notes": []}
        )
        return JudgeResult(
            payload=payload,
            provider="openai-codex",
            model="gpt-5.6-luna",
            effort="high",
            rubric_version="adw-rubric-v1",
            usage={"total_tokens": 1},
        )


def _rows(path: Path, digest: str, count: int, turn_id: str, tool_use_id: str) -> list[dict]:
    return [
        {
            "role": "comment", "path": str(path), "path_identity": str(path),
            "line": index, "text": f"candidate {index}", "content_hash": digest,
            "turn_id": turn_id, "tool_use_id": tool_use_id,
        }
        for index in range(count)
    ]


def test_candidate_journal_records_overflow_without_growing_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "a.py"
    state_root = tmp_path / "state"
    source.write_text("source\n", encoding="utf-8")
    monkeypatch.setattr(
        journal, "_candidate_rows",
        lambda path, digest, _text, turn_id, tool_use_id: _rows(
            path, digest, journal.MAX_ROWS + 1, turn_id, tool_use_id,
        ),
    )

    journal.record_edit("session", "turn-1", "tool-1", source, state_root=state_root)

    assert len(journal.read("session", state_root=state_root)) == journal.MAX_ROWS
    marker = journal.read_overflow("session", state_root=state_root)
    assert marker[0]["turn_id"] == "turn-1"
    assert marker[0]["omitted_count"] == 1


def test_codex_overflow_blocks_before_judging_and_recovers_after_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    source = tmp_path / "code.py"
    source.write_text("source\n", encoding="utf-8")
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    monkeypatch.setattr(
        journal, "_candidate_rows",
        lambda path, digest, _text, turn_id, tool_use_id: _rows(
            path, digest, codex_luna.MAX_COMMENT_ROWS + 1, turn_id, tool_use_id,
        ),
    )
    journal.record_edit("overflow", "turn-1", "tool-1", source, state_root=state_root)
    provider = Provider()
    payload = {"session_id": "overflow", "turn_id": "turn-1", "stop_hook_active": False, "cwd": str(tmp_path)}

    blocked = stop.run(payload, config, provider=provider)

    assert blocked["decision"] == "block"
    assert "truncated" in blocked["reason"]
    assert provider.calls == []
    assert codex_luna.STATE_KEY not in session_state.read_state("overflow", state_root)

    source.write_text("corrected\n", encoding="utf-8")
    monkeypatch.setattr(
        journal, "_candidate_rows",
        lambda path, digest, _text, turn_id, tool_use_id: _rows(path, digest, 1, turn_id, tool_use_id),
    )
    journal.record_edit("overflow", "turn-1", "tool-2", source, state_root=state_root)

    recovered = stop.run({**payload, "stop_hook_active": True}, config, provider=provider)

    assert recovered == {}
    assert len(provider.calls) == 1
    assert session_state.read_state("overflow", state_root)[codex_luna.STATE_KEY] == ["turn-1"]


def test_document_journal_keeps_the_tail_within_the_file_bound(tmp_path: Path) -> None:
    source = tmp_path / "draft.md"
    state_root = tmp_path / "state"
    source.write_text("a" * 24_000 + "\nTAIL", encoding="utf-8")

    journal.record_edit("session", "turn-1", "tool-1", source, state_root=state_root)

    rows = journal.read("session", state_root=state_root)
    document = next(row for row in rows if row["role"] == "document")
    assert document["source_context"].endswith("TAIL")
    assert document["source_truncated"] is False


def test_codex_rejects_a_truncated_comment_candidate_before_reserving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "code.py"
    source.write_text("source\n", encoding="utf-8")
    monkeypatch.setattr(journal, "candidates", lambda *_args: (Candidate(str(source), 1, "x" * 321),))
    journal.record_edit("session", "turn-1", "tool-1", source, state_root=tmp_path / "state")

    with pytest.raises(codex_luna.LunaReviewFailure, match="truncated a comment"):
        codex_luna._review_work({"session_id": "session"}, "turn-1", tmp_path / "state")


def test_overflow_markers_keep_another_target_blocked_during_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    state_root = tmp_path / "state"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    counts = {first.name: journal.MAX_ROWS + 1, second.name: journal.MAX_ROWS + 1}
    monkeypatch.setattr(
        journal, "_candidate_rows",
        lambda path, digest, _text, turn_id, tool_use_id: _rows(
            path, digest, counts[path.name], turn_id, tool_use_id,
        ),
    )

    journal.record_edit("session", "turn-1", "tool-1", first, state_root=state_root)
    journal.record_edit("session", "turn-1", "tool-2", second, state_root=state_root)
    markers = journal.read_overflow("session", state_root=state_root)
    assert {marker["path_identity"] for marker in markers} == {str(first), str(second)}

    counts[first.name] = 1
    first.write_text("first corrected\n", encoding="utf-8")
    journal.record_edit("session", "turn-1", "tool-3", first, state_root=state_root)
    markers = journal.read_overflow("session", state_root=state_root)
    assert {marker["path_identity"] for marker in markers} == {str(second)}

    counts[second.name] = 1
    second.write_text("second corrected\n", encoding="utf-8")
    journal.record_edit("session", "turn-1", "tool-4", second, state_root=state_root)
    assert journal.read_overflow("session", state_root=state_root) == []
