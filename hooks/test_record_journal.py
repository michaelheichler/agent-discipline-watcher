from __future__ import annotations

from pathlib import Path

import record
from lib import journal


def _edits(tmp_path: Path, session: str = "s1") -> record._EditJournal:
    return record._EditJournal(
        payload={
            "session_id": session,
            "tool_name": "Write",
            "tool_use_id": "t1",
            "cwd": str(tmp_path),
        },
        paths=["notes.md"],
        root=str(tmp_path / "ledger"),
        state_root=str(tmp_path / "state"),
    )


def test_an_edit_reaches_the_candidate_journal(tmp_path: Path) -> None:
    """Pinned because an empty journal reports every turn clean and nothing else notices."""
    (tmp_path / "notes.md").write_text("Let me know if you need anything else.\n", encoding="utf-8")

    record._journal_edits(_edits(tmp_path), "turn-1")

    rows = journal.read("s1", state_root=str(tmp_path / "state"))
    assert rows
    assert all(row["path"] == str(tmp_path / "notes.md") for row in rows)


def test_a_turn_without_a_session_writes_no_candidate(tmp_path: Path) -> None:
    """Skipped because a candidate keyed to no session is one the Stop hook can never find."""
    (tmp_path / "notes.md").write_text("Let me know if you need anything else.\n", encoding="utf-8")

    record._journal_edits(_edits(tmp_path, session=""), "turn-1")

    assert not (tmp_path / "state").exists()


def test_the_ledger_row_still_lands_for_a_sessionless_turn(tmp_path: Path) -> None:
    """Keep the ledger because it records the edit itself, which needs no session to be useful."""
    (tmp_path / "notes.md").write_text("text\n", encoding="utf-8")

    record._journal_edits(_edits(tmp_path, session=""), "turn-1")

    assert (tmp_path / "ledger").exists()
