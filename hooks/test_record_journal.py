from __future__ import annotations

from pathlib import Path

import pytest

import record
from lib import embedding_session, journal


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


@pytest.mark.parametrize("tool_input", [{"file_path": "notes.md"}, {"command": "ls"}])
def test_every_post_tool_use_renews_the_embedding_lease(tmp_path: Path, tool_input: dict) -> None:
    """Renewed, because a long turn outlives the lease TTL."""
    (tmp_path / "notes.md").write_text("text\n", encoding="utf-8")
    renewed: list[tuple[str, str | None]] = []
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    tool = "Write" if "file_path" in tool_input else "Bash"

    record.run({
        "session_id": "s1", "cwd": str(tmp_path), "tool_name": tool, "tool_use_id": "t1", "tool_input": tool_input,
    }, config, renew=lambda session, root: renewed.append((session, root)) or True)

    assert renewed == [("s1", embedding_session.lease_root_for(config))]


def test_a_sessionless_post_tool_use_renews_nothing(tmp_path: Path) -> None:
    record.run(
        {"cwd": str(tmp_path), "tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "ls"}}, {},
        renew=lambda *_args: pytest.fail("renewed without a session"),
    )


def test_the_ledger_row_still_lands_for_a_sessionless_turn(tmp_path: Path) -> None:
    """Keep the ledger because it records the edit itself, which needs no session to be useful."""
    (tmp_path / "notes.md").write_text("text\n", encoding="utf-8")

    record._journal_edits(_edits(tmp_path, session=""), "turn-1")

    assert (tmp_path / "ledger").exists()
