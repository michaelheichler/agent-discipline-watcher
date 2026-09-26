"""Split out because pattern rows arrive after the write."""
from __future__ import annotations

from pathlib import Path

from lib import journal, session_state

CLOSER = "Feel free to ask me anything else."


def _stored(state_root: Path) -> list[dict]:
    return session_state.read_state("session", state_root)[journal.STATE_KEY]


def _document(tmp_path: Path, text: str = f"{CLOSER}\n") -> tuple[Path, str]:
    path = tmp_path / "notes.md"
    path.write_text(text, encoding="utf-8")
    source = journal.current_source(path)
    assert source is not None
    return path, source[0]


def test_each_voted_sentence_becomes_one_pattern_row(tmp_path: Path) -> None:
    path, digest = _document(tmp_path)
    state_root = tmp_path / "state"

    journal.record_patterns(
        "session", "turn-1", path, [{"rule": "ai_closer", "line": 1, "text": CLOSER}],
        content_hash=digest, state_root=state_root,
    )

    [row] = _stored(state_root)
    assert (row["role"], row["rule"], row["line"], row["text"]) == ("pattern", "ai_closer", 1, CLOSER)
    assert (row["content_hash"], row["turn_id"]) == (digest, "turn-1")


def test_a_vote_on_text_that_changed_since_is_dropped(tmp_path: Path) -> None:
    path, digest = _document(tmp_path)
    path.write_text("The cache holds 4096 entries.\n", encoding="utf-8")
    state_root = tmp_path / "state"

    added = journal.record_patterns(
        "session", "turn-1", path, [{"rule": "ai_closer", "line": 1, "text": CLOSER}],
        content_hash=digest, state_root=state_root,
    )

    assert added == []
    assert session_state.read_state("session", state_root).get(journal.STATE_KEY) is None


def test_two_rules_on_one_sentence_keep_two_rows(tmp_path: Path) -> None:
    path, digest = _document(tmp_path)
    state_root = tmp_path / "state"
    rows = [{"rule": rule, "line": 1, "text": CLOSER} for rule in ("ai_closer", "utilize")]

    journal.record_patterns("session", "turn-1", path, rows, content_hash=digest, state_root=state_root)

    assert sorted(row["rule"] for row in _stored(state_root)) == ["ai_closer", "utilize"]


def test_an_edit_to_the_file_drops_its_old_pattern_rows(tmp_path: Path) -> None:
    path, digest = _document(tmp_path)
    state_root = tmp_path / "state"
    journal.record_patterns(
        "session", "turn-1", path, [{"rule": "ai_closer", "line": 1, "text": CLOSER}],
        content_hash=digest, state_root=state_root,
    )
    path.write_text("The cache holds 4096 entries.\n", encoding="utf-8")

    journal.record_edit("session", "turn-2", "tool", path, state_root=state_root)

    assert [row["role"] for row in _stored(state_root)] == ["document"]


def test_one_file_contributes_a_bounded_number_of_rows(tmp_path: Path) -> None:
    path, digest = _document(tmp_path)
    state_root = tmp_path / "state"
    rows = [{"rule": "ai_closer", "line": line, "text": f"{CLOSER} {line}"} for line in range(100)]

    journal.record_patterns("session", "turn-1", path, rows, content_hash=digest, state_root=state_root)

    assert len(_stored(state_root)) == journal.MAX_PATTERN_ROWS_PER_FILE
