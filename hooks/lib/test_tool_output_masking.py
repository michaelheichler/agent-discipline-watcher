"""Through scan_all, because saved command output must stay quiet while prose the agent wrote beside it still reports."""
from __future__ import annotations

import json

import pytest

from lib.scanner import scan_all

DASH = chr(0x2014)
PROSE = f"It is important to note that the build failed {DASH} and nobody saw it.\n"
DIFF_HEADERS = "--- a/notes.md\n+++ b/notes.md\n@@ -1 +1 @@\n"


def _rows(path: str, text: str) -> list[tuple[str, int]]:
    return [(row["rule"], row["line"]) for row in scan_all(path, text, {})]


def _dash_lines(path: str, text: str) -> list[int]:
    return [line for rule, line in _rows(path, text) if rule == "banned_dash"]


@pytest.mark.parametrize(("path", "text"), [
    pytest.param("run.log", PROSE, id="log-file"),
    pytest.param("reply.txt", json.dumps({"note": PROSE.strip()}, ensure_ascii=False, indent=2) + "\n", id="json-document-in-txt"),
    pytest.param("hits.txt", f"src/app.py:12:{PROSE}", id="rg-match-line"),
    pytest.param("hits.out", f"src/app.py-12-{PROSE}", id="grep-context-line"),
    pytest.param("run.text", f"2026-10-24 12:30:01 {PROSE}", id="timestamped-line"),
    pytest.param("run.txt", f"[12:30:01] {PROSE}", id="bracketed-clock-line"),
    pytest.param("change.txt", f"{DIFF_HEADERS}-Old text.\n+{PROSE}", id="unified-diff"),
])
def test_saved_tool_output_in_a_plain_text_file_reports_nothing(path: str, text: str) -> None:
    assert _rows(path, text) == []


@pytest.mark.parametrize(("path", "text", "lines"), [
    pytest.param("notes.txt", PROSE, [1], id="authored-prose-in-txt"),
    pytest.param("hits.txt", f"src/app.py:12:{PROSE}{PROSE}", [2], id="prose-after-a-match-line"),
    pytest.param("change.txt", f"+{PROSE}", [1], id="diff-prefix-without-headers"),
    pytest.param("notes.md", f"src/app.py:12:{PROSE}", [1], id="match-like-line-in-markdown"),
    pytest.param("notes.md", f"2026-10-24 12:30:01 {PROSE}", [1], id="timestamp-like-line-in-markdown"),
])
def test_prose_beside_or_shaped_like_tool_output_still_reports(path: str, text: str, lines: list[int]) -> None:
    assert _dash_lines(path, text) == lines


def test_a_json_document_in_markdown_still_reports() -> None:
    text = json.dumps({"note": PROSE.strip()}, ensure_ascii=False) + "\n"

    assert _rows("notes.md", text) != []
