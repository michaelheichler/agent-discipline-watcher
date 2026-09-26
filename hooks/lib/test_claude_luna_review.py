"""Split out because the Luna request shape has its own contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import claude_luna


def _post_payload(path: Path) -> dict:
    return {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(path.parent),
        "tool_name": "Write", "tool_use_id": "tool-1",
        "tool_input": {"file_path": str(path), "content": "raw host content"},
    }


@pytest.mark.parametrize(("name", "comment"), (
    ("a.ts", "// Counts the retries because the report header needs a total."),
    ("a.sh", "# Counts the retries because the report header needs a total."),
    ("a.go", "// Counts the retries because the report header needs a total."),
))
def test_the_comment_reviewer_reads_every_commentable_language(tmp_path: Path, name: str, comment: str) -> None:
    source = tmp_path / name
    source.write_text(f"{comment}\nvalue = 1\n", encoding="utf-8")

    built = claude_luna.post_request(_post_payload(source))

    assert built is not None
    assert "Counts the retries" in built[1][0].text


def test_the_comment_reviewer_skips_a_file_with_no_comment_syntax(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("# Counts the retries because the report header needs a total.\n", encoding="utf-8")

    assert claude_luna.post_request(_post_payload(source)) is None
