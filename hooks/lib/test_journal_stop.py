"""Split out because the Stop read has its own turn and budget contract."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from lib import journal, session_state


def _document(path: Path, digest: str, turn_id: str = "") -> dict:
    return {
        "role": "document", "path": str(path), "path_identity": str(path),
        "content_hash": digest, "source_context": "x" * 10, "turn_id": turn_id,
    }


def _store(tmp_path: Path, rows: list[dict]) -> Path:
    state_root = tmp_path / "state"
    session_state.write_state("session", {journal.STATE_KEY: rows}, state_root)
    return state_root


def test_stop_read_keeps_one_latest_row_per_path(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    state_root = _store(tmp_path, [_document(doc, "old"), _document(doc, "new")])

    rows = journal.read_stop("session", state_root=state_root)

    assert [row["content_hash"] for row in rows] == ["new"]


def test_stop_read_keeps_the_current_turn_and_unreviewed_rows_only(tmp_path: Path) -> None:
    state_root = _store(tmp_path, [
        _document(tmp_path / "reviewed.md", "a", "turn-1"),
        _document(tmp_path / "now.md", "b", "turn-2"),
        _document(tmp_path / "pending.md", "c", "turn-1"),
    ])
    session_state.update_state("session", lambda state: {**state, "turn_id": "turn-2"}, state_root)
    everything = journal.read_stop("session", state_root=state_root)
    journal.mark_reviewed("session", everything[:2], state_root=state_root)

    rows = journal.read_stop("session", state_root=state_root)

    assert [Path(row["path"]).name for row in rows] == ["now.md", "pending.md"]


def test_stop_read_applies_one_aggregate_character_budget(tmp_path: Path) -> None:
    documents = [
        {**_document(tmp_path / f"{index}.md", str(index)), "source_context": "x" * 20_000}
        for index in range(5)
    ]
    state_root = _store(tmp_path, documents)

    rows = journal.read_stop("session", state_root=state_root)

    assert sum(len(row["source_context"]) for row in rows) <= journal.MAX_STOP_TOTAL_CHARS == 48_000
    assert len(rows) == 2


def test_the_stop_helper_serves_an_earlier_document_once(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    document.write_text("Served to one Stop reviewer.\n", encoding="utf-8")
    journal.record_edit("session", "turn", "tool", document, state_root=tmp_path / ".adw" / "state")
    reader = Path(__file__).parents[1] / "read_claude_journal.sh"

    def read() -> str:
        result = subprocess.run(
            [str(reader), "--documents", "session"], env={**os.environ, "HOME": str(tmp_path)},
            capture_output=True, text=True, check=True,
        )
        return result.stdout

    assert "Served to one Stop reviewer." in read()
    assert read().strip() == "[]"


def test_stop_read_skips_a_reviewed_digest_until_the_content_changes(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    state_root = _store(tmp_path, [_document(doc, "first")])
    journal.mark_reviewed("session", journal.read_stop("session", state_root=state_root), state_root=state_root)

    assert journal.read_stop("session", state_root=state_root) == []

    session_state.update_state(
        "session", lambda state: {**state, journal.STATE_KEY: [_document(doc, "second")]}, state_root,
    )
    assert [row["content_hash"] for row in journal.read_stop("session", state_root=state_root)] == ["second"]


def _pattern(path: Path, digest: str, line: int, turn_id: str = "") -> dict:
    return {
        "role": "pattern", "rule": "ai_closer", "path": str(path), "path_identity": str(path),
        "line": line, "text": f"Feel free to ask me anything else {line}.", "content_hash": digest,
        "turn_id": turn_id,
    }


def test_stop_read_serves_pattern_rows_ahead_of_documents(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    state_root = _store(tmp_path, [_document(doc, "one"), _pattern(doc, "one", 3)])

    rows = journal.read_stop("session", state_root=state_root)

    assert [row["role"] for row in rows] == ["pattern", "document"]
    assert rows[0] == {
        "role": "pattern", "path": str(doc), "content_hash": "one", "rule": "ai_closer",
        "line": 3, "text": "Feel free to ask me anything else 3.",
    }


def test_pattern_rows_count_against_the_same_character_budget(tmp_path: Path) -> None:
    documents = [
        {**_document(tmp_path / f"{index}.md", str(index)), "source_context": "x" * 20_000}
        for index in range(3)
    ]
    patterns = [_pattern(tmp_path / "p.md", "p", line) for line in range(30)]
    state_root = _store(tmp_path, [*documents, *patterns])

    rows = journal.read_stop("session", state_root=state_root)

    assert [row["role"] for row in rows].count("pattern") == 30
    assert sum(len(row.get("source_context", row.get("text", ""))) for row in rows) <= journal.MAX_STOP_TOTAL_CHARS


def test_a_vote_that_lands_after_its_document_was_reviewed_is_still_served(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    state_root = _store(tmp_path, [_document(doc, "one", "turn-1")])
    journal.mark_reviewed("session", journal.read_stop("session", state_root=state_root), state_root=state_root)
    session_state.update_state(
        "session",
        lambda state: {**state, "turn_id": "turn-2", journal.STATE_KEY: [*state[journal.STATE_KEY], _pattern(doc, "one", 1, "turn-1")]},
        state_root,
    )

    rows = journal.read_stop("session", state_root=state_root)
    journal.mark_reviewed("session", rows, state_root=state_root)

    assert [row["role"] for row in rows] == ["pattern"]
    assert journal.read_stop("session", state_root=state_root) == []


def test_a_document_gets_two_review_rounds_at_most(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    state_root = _store(tmp_path, [])
    served = []
    for digest in ("first", "second", "third"):
        session_state.update_state(
            "session", lambda state, digest=digest: {**state, journal.STATE_KEY: [_document(doc, digest)]}, state_root,
        )
        rows = journal.read_stop("session", state_root=state_root)
        journal.mark_reviewed("session", rows, state_root=state_root)
        served.extend(row["content_hash"] for row in rows)

    assert served == ["first", "second"]
    assert journal.MAX_DOCUMENT_ROUNDS == 2
