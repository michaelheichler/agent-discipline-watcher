"""Kept apart from the dash tests, because a dash look-alike breaks a clause only in some positions."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

MINUS = chr(0x2212)
NON_BREAKING_HYPHEN = chr(0x2011)


def _dash_lines(text: str, path: str = "doc.md") -> list[int]:
    return [row["line"] for row in scan_all(path, text, {}) if row["rule"] == "banned_dash"]


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


@pytest.mark.parametrize(("path", "text"), [
    pytest.param("doc.md", f"The rock{NON_BREAKING_HYPHEN}wall texture loads.\n", id="prose-compound"),
    pytest.param(".build/poly.json", f'{{"name": "rock{NON_BREAKING_HYPHEN}wall"}}\n', id="entry-19-json-name"),
])
def test_a_non_breaking_hyphen_inside_a_word_draws_no_banned_dash(path: str, text: str) -> None:
    assert _dash_lines(text, path) == []


@pytest.mark.parametrize("text", [
    pytest.param(f"The house {NON_BREAKING_HYPHEN} and the barn burned.\n", id="spaced-non-breaking-hyphen"),
    pytest.param(f"The house{chr(0x2014)}and the barn burned.\n", id="em-dash-between-words"),
])
def test_a_dash_that_breaks_a_clause_still_reports_a_banned_dash(text: str) -> None:
    assert _dash_lines(text) == [1]
