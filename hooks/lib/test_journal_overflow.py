from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

import stop
from lib import codex_luna, journal, session_state
from lib.judge import Candidate
from lib.judge_contracts import RUBRIC_VERSION, JudgeRequest, JudgeResult, ReviewKind


@pytest.fixture(autouse=True)
def _open_data_boundary(tmp_path: Path) -> None:
    """Opened here, because the gate has its own test file."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"data_boundary": {"enabled": True}}), encoding="utf-8")


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
            rubric_version=RUBRIC_VERSION,
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


def _candidate_count(monkeypatch: pytest.MonkeyPatch, count: object) -> None:
    """A callable count, because one test varies it per path."""
    def rows(path: Path, digest: str, _text: str, turn_id: str, tool_use_id: str) -> list[dict]:
        total = count(path) if callable(count) else count
        return _rows(path, digest, total, turn_id, tool_use_id)

    monkeypatch.setattr(journal, "_candidate_rows", rows)


def test_candidate_journal_records_overflow_without_growing_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "a.py"
    state_root = tmp_path / "state"
    source.write_text("source\n", encoding="utf-8")
    _candidate_count(monkeypatch, journal.MAX_ROWS + 1)

    journal.record_edit("session", "turn-1", "tool-1", source, state_root=state_root)

    assert len(journal.read("session", state_root=state_root)) == journal.MAX_ROWS
    marker = journal.read_overflow("session", state_root=state_root)
    assert marker[0]["turn_id"] == "turn-1"
    assert marker[0]["omitted_count"] == 1


def test_codex_overflow_blocks_before_judging_and_recovers_after_correction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = tmp_path / "state"
    source = tmp_path / "code.py"
    source.write_text("source\n", encoding="utf-8")
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    _candidate_count(monkeypatch, codex_luna.MAX_COMMENT_ROWS + 1)
    journal.record_edit("overflow", "turn-1", "tool-1", source, state_root=state_root)
    provider = Provider()
    payload = {"session_id": "overflow", "turn_id": "turn-1", "stop_hook_active": False, "cwd": str(tmp_path)}

    blocked = stop.run(payload, config, provider=provider)

    assert blocked["decision"] == "block"
    assert "truncated" in blocked["reason"]
    assert provider.calls == []
    assert codex_luna.STATE_KEY not in session_state.read_state("overflow", state_root)

    source.write_text("corrected\n", encoding="utf-8")
    _candidate_count(monkeypatch, 1)
    journal.record_edit("overflow", "turn-1", "tool-2", source, state_root=state_root)

    recovered = stop.run({**payload, "stop_hook_active": True}, config, provider=provider)

    assert recovered == {}
    assert len(provider.calls) == 1
    assert session_state.read_state("overflow", state_root)[codex_luna.STATE_KEY] == ["turn-1"]


def test_old_turn_overflow_stays_blocked_until_the_path_is_refreshed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    source = tmp_path / "code.py"
    source.write_text("source\n", encoding="utf-8")
    _candidate_count(monkeypatch, codex_luna.MAX_COMMENT_ROWS + 1)
    journal.record_edit("overflow-old-turn", "turn-old", "tool-1", source, state_root=state_root)

    with pytest.raises(codex_luna.LunaReviewFailure, match="truncated"):
        codex_luna._journal_rows(
            {"session_id": "overflow-old-turn"}, "turn-new", state_root,
        )


def test_full_overflow_metadata_requires_a_new_codex_session(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    session_state.write_state(
        "overflow-sentinel",
        {
            journal.OVERFLOW_KEY: {
                journal.OVERFLOW_SENTINEL: {
                    "path_identity": journal.OVERFLOW_SENTINEL,
                    "content_hash": "",
                    "turn_id": "",
                    "candidate_count": journal.MAX_ROWS + 1,
                    "omitted_count": 1,
                },
            },
        },
        state_root,
    )

    with pytest.raises(codex_luna.LunaReviewFailure):
        codex_luna._journal_rows(
            {"session_id": "overflow-sentinel"}, "turn-new", state_root,
        )

    assert [
        (marker["candidate_count"], marker["omitted_count"])
        for marker in journal.read_overflow("overflow-sentinel", state_root=state_root)
    ] == [(journal.MAX_ROWS + 1, 1)]


def test_legacy_document_prefix_is_rejected_before_review(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    session_state.write_state(
        "legacy-document",
        {
            journal.STATE_KEY: [{
                "role": "document",
                "path": "draft.md",
                "source_context": "x" * journal.MAX_STOP_DOCUMENT_CHARS,
                "turn_id": "turn-1",
            }],
        },
        state_root,
    )

    with pytest.raises(codex_luna.LunaReviewFailure, match="truncated"):
        codex_luna._review_work(
            {"session_id": "legacy-document"}, "turn-1", state_root,
        )


def test_same_hash_edit_replaces_a_legacy_document_prefix(tmp_path: Path) -> None:
    source = tmp_path / "draft.md"
    state_root = tmp_path / "state"
    full_source = "a" * journal.MAX_STOP_DOCUMENT_CHARS + "\nTAIL"
    source.write_text(full_source, encoding="utf-8")
    journal.record_edit("legacy-refresh", "turn-1", "tool-1", source, state_root=state_root)

    def downgrade(state: dict) -> dict:
        rows = []
        for row in state[journal.STATE_KEY]:
            updated = dict(row)
            if updated.get("role") == "document":
                updated.pop("source_truncated", None)
                updated["source_context"] = full_source[: journal.MAX_STOP_DOCUMENT_CHARS]
            rows.append(updated)
        return {**state, journal.STATE_KEY: rows}

    session_state.update_state("legacy-refresh", downgrade, state_root)
    journal.record_edit("legacy-refresh", "turn-2", "tool-2", source, state_root=state_root)

    documents = [row for row in journal.read("legacy-refresh", state_root=state_root) if row.get("role") == "document"]
    assert len(documents) == 1
    assert documents[0]["source_context"].endswith("TAIL")
    assert documents[0]["source_truncated"] is False


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


def test_overflow_markers_keep_another_target_blocked_during_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    state_root = tmp_path / "state"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    counts = {first.name: journal.MAX_ROWS + 1, second.name: journal.MAX_ROWS + 1}
    _candidate_count(monkeypatch, lambda path: counts[path.name])

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


def test_complete_journal_rejects_overflow_from_the_same_single_snapshot(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    root = tmp_path / "state"
    rows = _rows(source, "digest", 1, "turn", "tool")
    marker = {"path_identity": str(source), "turn_id": "turn", "candidate_count": 2, "omitted_count": 1}
    session_state.write_state("complete", {journal.STATE_KEY: rows, journal.OVERFLOW_KEY: {str(source): marker}}, root)
    opened = []
    open_file = io.open

    def observed(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(io, "open", observed)

    with pytest.raises(ValueError):
        journal.read_complete("complete", state_root=root, project=tmp_path)
    assert len([path for path in opened if Path(path).name == session_state.STATE_FILENAME]) == 1


def test_complete_journal_accepts_absent_state(tmp_path) -> None:
    assert journal.read_complete("empty", state_root=tmp_path / "state", project=tmp_path) == []


@pytest.mark.parametrize("rows", [
    pytest.param({}, id="mapping"),
    pytest.param("rows", id="string"),
    pytest.param([None], id="invalid-member"),
])
def test_complete_journal_rejects_malformed_candidate_containers(tmp_path, rows) -> None:
    root = tmp_path / "state"
    session_state.write_state("malformed", {journal.STATE_KEY: rows}, root)

    with pytest.raises(ValueError):
        journal.read_complete("malformed", state_root=root, project=tmp_path)


def test_loaded_unknown_home_candidates_keep_their_canonical_literal_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    raw = "~adw_nonexistent_user_874932/source.py"
    row = {"role": "comment", "path": raw, "line": 1, "text": "reason", "content_hash": "digest"}
    root = tmp_path / "state"
    session_state.write_state("literal", {journal.STATE_KEY: [row]}, root)

    [loaded] = journal.read_complete("literal", state_root=root, project=tmp_path)

    assert journal.candidate_key(loaded)[1] == str((tmp_path / raw).resolve())
