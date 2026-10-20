"""German hits sit on their own lines, because a paragraph span made an edit anywhere in it own every hit."""
from __future__ import annotations

import pytest

from lib.provenance import compare
from lib.scanner import scan_all

GERMAN_ONLY = {"prose_languages": ["de"]}
COMPANY_PARAGRAPH = (
    "Die afiTec GmbH baut lediglich gute Pumpen für Kunden.\n"
    "Sie liefert jedes Gerät pünktlich an jeden Ort.\n"
    "Die Donaudampfschifffahrtsgesellschaft prüft das eigentlich genau.\n"
)
CONNECTOR_PARAGRAPH = (
    "Außerdem kam der Hund heute nach Hause.\n"
    "Außerdem ging er wieder in den Garten.\n"
    "Außerdem schlief er dort sehr lange.\n"
)
UNFINISHED_PARAGRAPH = "Die Stadt liegt am Fluss.\nSie hat einen Hafen.\nDie Gründung der Stadt war\n"
BARE_BULLETS = (
    "Intro Satz steht hier.\n\nNoch ein Absatz mit Text hier.\n\nDie Liste folgt jetzt:\n\n"
    "- Pumpen.\n- Ventile.\n- Rohre.\n"
)


def _lines(text: str, rule: str) -> list[tuple[int, int | None]]:
    return [(row["line"], row.get("end_line")) for row in scan_all("doc.md", text, GERMAN_ONLY) if row["rule"] == rule]


def _ownership(before: str, after: str, rules: set[str]) -> list[tuple[str, int, bool]]:
    result = compare("doc.md", before, after)
    rows = scan_all("doc.md", after, GERMAN_ONLY)
    return sorted((row["rule"], row["line"], result.owns(row)) for row in rows if row["rule"] in rules)


@pytest.mark.parametrize("rule", ["de_long_compound", "de_filler_word"])
def test_a_german_word_hit_reports_the_line_that_holds_the_word(rule: str) -> None:
    text = COMPANY_PARAGRAPH.replace("lediglich ", "")

    assert _lines(text, rule) == [(3, None)]


def test_a_german_phrase_across_a_line_break_reports_its_first_and_last_line() -> None:
    text = "Der Hund schlief lange.\nDann lief er durch den Park und war am Ende\ndes Tages froh über den Ausflug.\n"

    assert _lines(text, "de_anglicism") == [(2, 3)]


def test_each_bare_bullet_item_reports_its_own_line() -> None:
    assert _lines(BARE_BULLETS, "de_bullet_punctuation") == [(7, None), (8, None), (9, None)]


def test_a_one_word_edit_owns_only_the_german_hits_in_the_edited_sentence() -> None:
    after = COMPANY_PARAGRAPH.replace("afiTec", "afITec")

    assert _ownership(COMPANY_PARAGRAPH, after, {"de_long_compound", "de_filler_word"}) == [
        ("de_filler_word", 1, True), ("de_filler_word", 3, False), ("de_long_compound", 3, False),
    ]


@pytest.mark.parametrize(("rule", "before", "after"), [
    pytest.param(
        "de_repeated_connector", CONNECTOR_PARAGRAPH, CONNECTOR_PARAGRAPH.replace("Garten", "Wald"),
        id="de_repeated_connector"),
    pytest.param(
        "de_abrupt_ending", UNFINISHED_PARAGRAPH, UNFINISHED_PARAGRAPH.replace("Hafen", "Markt"), id="de_abrupt_ending"),
])
def test_a_german_paragraph_finding_is_owned_when_any_sentence_in_it_changes(rule: str, before: str, after: str) -> None:
    assert _ownership(before, after, {rule}) == [(rule, 1, True)]
