"""German rhythm must survive paragraphs without words, because the rule runs before its gate and a crash drops every finding in the file."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

EQUAL_SENTENCES = "Der Hund lief heute schnell durch den Park. Die Katze schlief heute lange auf dem Sofa."


def _rhythm_lines(text: str, config: dict) -> list[int]:
    return [row["line"] for row in scan_all("doc.md", text, config) if row["rule"] == "de_uniform_rhythm"]


@pytest.mark.parametrize("gate", ("off", "enforce"))
def test_paragraphs_without_words_scan_with_no_rhythm_finding(gate: str) -> None:
    config = {"prose_languages": ["de"], "rule_gates": {"de_uniform_rhythm": gate}}
    text = "\n\n".join(["123"] * 8) + "\n"

    assert _rhythm_lines(text, config) == []


def test_a_wordless_paragraph_does_not_hide_uniform_rhythm_in_the_prose_around_it() -> None:
    text = "\n\n".join([EQUAL_SENTENCES] * 4 + ["2026"] + [EQUAL_SENTENCES] * 4) + "\n"

    assert _rhythm_lines(text, {"prose_languages": ["de"]}) == [1]
