from pathlib import Path

import pytest

from lib import codex_luna, journal
from lib.narration_candidates import candidates


@pytest.mark.parametrize("suffix, prefix", [(".py", "#"), (".ts", "//")])
def test_distinct_comments_survive_journal_and_review(tmp_path: Path, suffix: str, prefix: str) -> None:
    target = tmp_path / f"code{suffix}"
    source = (
        f"{prefix} Returns the cache because callers need stable identity.\n"
        f"{prefix} Counts the rows because the report header needs a total before the body renders.\n"
    )
    target.write_text(source, encoding="utf-8")
    state = tmp_path / "state"
    assert len(candidates(str(target), source)) == 2

    journal.record_edit("review-coverage", "turn-1", "tool-1", target, state_root=state)
    journal.record_edit("review-coverage", "turn-1", "tool-2", target, state_root=state)

    stored = journal.read("review-coverage", state_root=state)
    assert [row["line"] for row in stored if row["role"] == "comment"] == [1, 2]
    reviewed = codex_luna._journal_rows({"session_id": "review-coverage"}, "turn-1", state)
    assert [row["line"] for row in reviewed if row["role"] == "comment"] == [1, 2]
