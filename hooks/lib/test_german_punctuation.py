"""Pinned by behavior, because a German paragraph held to the English bans blocks correct Duden typography."""
from __future__ import annotations

import pytest

from lib.german_punctuation import DASH_CLUSTER_MIN_COUNT, DASH_CLUSTER_MIN_PER_1000_WORDS
from lib.scanner import scan_all

GERMAN_TAIL = "weil wir das so wollen und es nicht anders geht."
ENGLISH_TAIL = "because we want it that way and there is no other path."
GERMAN_FILLER = "Wir bauen das Haus, weil es nicht anders geht und wir das so wollen."


def _rules(text: str, config: dict | None = None) -> list[str]:
    return [row["rule"] for row in scan_all("doc.md", text + "\n", config)]


def _dashed(count: int) -> str:
    return " – ".join(["Das ist so"] * (count + 1)) + "."


def test_the_ergaenzungsstrich_raises_no_spaced_hyphen_in_german() -> None:
    assert _rules(f"Wir bauen den Ein- und Ausgang neu, {GERMAN_TAIL}") == []


def test_a_spaced_hyphen_still_reports_in_german() -> None:
    assert _rules(f"Wir bauen das Haus - und es dauert, {GERMAN_TAIL}") == ["spaced_hyphen"]


def test_a_spaced_gedankenstrich_passes_in_german() -> None:
    assert _rules(f"Wir bauen das Haus – und es dauert, {GERMAN_TAIL}") == []


def test_the_same_dash_still_reports_in_english() -> None:
    assert _rules(f"We build the house – and it takes time, {ENGLISH_TAIL}") == ["banned_dash"]


def test_a_long_german_sentence_reaches_the_document_rules_through_the_scanner() -> None:
    german = " ".join([GERMAN_FILLER.rstrip(".")] * 3) + "."
    english = " ".join([ENGLISH_TAIL.rstrip(".")] * 3) + "."

    assert "de_sentence_length" in _rules(german)
    assert "de_sentence_length" not in _rules(english)


def test_the_english_rules_leave_german_paragraphs_alone() -> None:
    german = " ".join([GERMAN_FILLER.rstrip(".")] * 3) + "."

    assert "long_sentence" not in _rules(german, {"sentence_word_cap": 20})
    assert "long_sentence" in _rules(" ".join([ENGLISH_TAIL.rstrip(".")] * 3) + ".", {"sentence_word_cap": 20})


@pytest.mark.parametrize("route", ["Puttgarden–Rødbyhavn", "63 v.–23 n. Chr."])
def test_a_streckenstrich_passes_in_german(route: str) -> None:
    assert _rules(f"Die Fähre fährt die Linie {route} seit Jahren, {GERMAN_TAIL}") == []


def test_a_bis_strich_between_numbers_passes_in_german() -> None:
    assert _rules(f"Das Haus stand von 1990–2000 leer, {GERMAN_TAIL}") == []


def test_the_em_dash_stays_banned_in_german() -> None:
    assert _rules(f"Wir bauen das Haus — und es dauert, {GERMAN_TAIL}") == ["banned_dash"]


def test_gedankenstriche_pass_below_the_count() -> None:
    assert _rules(_dashed(DASH_CLUSTER_MIN_COUNT - 1)) == []


def test_a_dense_run_of_gedankenstriche_reports_one_cluster() -> None:
    assert _rules(_dashed(DASH_CLUSTER_MIN_COUNT)) == ["dash_cluster"]


def test_enough_dashes_pass_when_the_text_is_long_enough() -> None:
    words_needed = int(DASH_CLUSTER_MIN_COUNT * 1000 / DASH_CLUSTER_MIN_PER_1000_WORDS) + 1
    filler = " ".join([GERMAN_FILLER] * (words_needed // len(GERMAN_FILLER.split()) + 1))

    assert "dash_cluster" not in _rules(_dashed(DASH_CLUSTER_MIN_COUNT) + "\n\n" + filler)


@pytest.mark.parametrize("quoted", ["„hallo“", "‚hallo‘"])
def test_german_quote_pairs_pass(quoted: str) -> None:
    assert _rules(f"Er sagte {quoted} und ging, {GERMAN_TAIL}") == []


@pytest.mark.parametrize("quoted", ['"hallo"', "“hallo”", "„hallo”", "'hallo'"])
def test_straight_and_english_quotes_report_in_german(quoted: str) -> None:
    assert _rules(f"Er sagte {quoted} und ging, {GERMAN_TAIL}") == ["quote_marks"]


@pytest.mark.parametrize("mark", [":", ";"])
def test_colon_and_semicolon_pass_in_german(mark: str) -> None:
    assert _rules(f"Wir bauen das Haus{mark} es dauert, {GERMAN_TAIL}") == []


def test_an_english_genitive_apostrophe_reports_in_german() -> None:
    assert _rules(f"Das ist Peter's Buch, {GERMAN_TAIL}") == ["genitive_apostrophe"]


def test_an_elided_es_passes_in_german() -> None:
    assert _rules(f"Wie geht's dir heute, {GERMAN_TAIL}") == []


@pytest.mark.parametrize("ellipsis", ["...", "…."])
def test_a_typed_ellipsis_reports_in_german(ellipsis: str) -> None:
    assert _rules(f"Wir bauen das Haus{ellipsis} und es dauert, {GERMAN_TAIL}") == ["typed_ellipsis"]


def test_each_prose_finding_carries_its_paragraph_language() -> None:
    text = f"We build the house; it takes time, {ENGLISH_TAIL}\n\nEr sagte \"hallo\" und ging, {GERMAN_TAIL}\n"
    rows = scan_all("doc.md", text)

    assert [(row["rule"], row["language"]) for row in rows] == [("prose_semicolon", "en"), ("quote_marks", "de")]


def test_english_only_projects_keep_german_text_on_the_english_rules() -> None:
    assert _rules(f"Wir bauen das Haus; es dauert, {GERMAN_TAIL}", {"prose_languages": ["en"]}) == ["prose_semicolon"]
