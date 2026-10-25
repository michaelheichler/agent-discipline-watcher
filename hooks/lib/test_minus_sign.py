"""Kept apart from the dash tests, because a minus sign is a dash only where it joins two words."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

MINUS = chr(0x2212)


def _dash_lines(text: str) -> list[int]:
    return [row["line"] for row in scan_all("doc.md", text, {}) if row["rule"] == "banned_dash"]


@pytest.mark.parametrize("text", [
    pytest.param(f"It was {MINUS}5 degrees outside today.\n", id="negative-temperature"),
    pytest.param(f"The offset drops to {MINUS}12 px.\n", id="negative-offset"),
    pytest.param(f"The zoom out key is {MINUS}.\n", id="lone-glyph"),
])
def test_a_minus_sign_outside_a_clause_break_passes(text: str) -> None:
    assert _dash_lines(text) == []


@pytest.mark.parametrize("text", [
    pytest.param(f"The house {MINUS} and the barn burned.\n", id="spaced"),
    pytest.param(f"The house{MINUS}and the barn burned.\n", id="unspaced"),
])
def test_a_minus_sign_between_two_words_reports_a_banned_dash(text: str) -> None:
    assert _dash_lines(text) == [1]
