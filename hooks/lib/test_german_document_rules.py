"""Each German rule is shown firing and staying quiet, because a rule that fires on clean text trains writers to ignore it."""
from __future__ import annotations

import pytest

from lib.german_document_rules import scan_german_document
from lib.prose_language import ParagraphLanguage

LONG_REAL_SENTENCE = (
    "Der Bericht zeigt, dass die Messung auf dem deutschen Korpus noch nicht abgeschlossen ist "
    "und wir die Schwelle deshalb erst später festlegen."
)


def _sentence(word_count: int) -> str:
    return " ".join(["Hund"] * word_count) + "."


def _paragraph(line: int, *word_counts: int) -> ParagraphLanguage:
    return _text_paragraph(line, " ".join(_sentence(count) for count in word_counts))


def _text_paragraph(line: int, text: str) -> ParagraphLanguage:
    return ParagraphLanguage(line=line, text=text, language="de", weak=False)


def _scan(paragraphs: list[ParagraphLanguage]) -> list[dict]:
    return scan_german_document("doc.md", paragraphs, {})


def _rule_ids(paragraphs: list[ParagraphLanguage]) -> list[str]:
    return [row["rule"] for row in _scan(paragraphs)]


def test_an_over_long_sentence_is_reported_with_its_line_and_text() -> None:
    rows = _scan([_paragraph(3, 21)])

    assert [(row["rule"], row["line"], row["snippet"]) for row in rows] == [("de_sentence_length", 3, _sentence(21))]


def test_each_over_long_sentence_gets_its_own_row() -> None:
    assert _rule_ids([_paragraph(1, 21, 4, 25)]) == ["de_sentence_length", "de_sentence_length"]


def test_short_sentences_raise_nothing() -> None:
    assert _rule_ids([_text_paragraph(1, "Der Hund lief. Die Katze schlief.")]) == []


def test_ten_sentences_of_equal_length_read_as_uniform_rhythm() -> None:
    assert _rule_ids([_paragraph(1, 8, 8, 8, 8, 8), _paragraph(2, 8, 8, 8, 8, 8)]) == ["de_uniform_rhythm"]


@pytest.mark.parametrize("paragraphs", (
    pytest.param([_paragraph(1, 8, 8, 8, 8, 8, 8, 8)], id="too-few-sentences-to-judge"),
    pytest.param([_paragraph(1, 2, 18, 2, 18, 2), _paragraph(2, 18, 2, 18, 2, 18)], id="lengths-vary-widely"),
))
def test_rhythm_stays_quiet_without_enough_uniform_sentences(paragraphs: list[ParagraphLanguage]) -> None:
    assert _rule_ids(paragraphs) == []


def test_four_paragraphs_of_equal_sentence_count_read_as_isometric() -> None:
    paragraphs = [_paragraph(line, 2, 12) for line in (1, 3, 5, 7)]

    assert _rule_ids(paragraphs) == ["de_uniform_paragraphs"]


@pytest.mark.parametrize("paragraphs", (
    pytest.param([_paragraph(line, 2, 12) for line in (1, 3, 5)], id="too-few-paragraphs"),
    pytest.param(
        [_paragraph(1, 2), _paragraph(3, 2, 12, 2, 12, 2), _paragraph(5, 12, 2), _paragraph(7, 2, 12)],
        id="paragraph-lengths-spread-out",
    ),
))
def test_isometric_document_stays_quiet_for_few_or_varied_paragraphs(paragraphs: list[ParagraphLanguage]) -> None:
    assert _rule_ids(paragraphs) == []


@pytest.mark.parametrize("text", (
    "Außerdem kam er. Außerdem ging er wieder.",
    "Darüber hinaus regnete es. Ferner fiel Schnee.",
))
def test_two_sentences_opening_on_a_stock_connector_are_flagged(text: str) -> None:
    assert _rule_ids([_text_paragraph(1, text)]) == ["de_repeated_connector"]


@pytest.mark.parametrize("text", (
    pytest.param("Außerdem kam er. Dann ging er wieder.", id="one-connector-opener"),
    pytest.param("Er kam außerdem. Sie ging ebenfalls.", id="connectors-mid-sentence"),
))
def test_a_single_connector_opener_is_allowed(text: str) -> None:
    assert _rule_ids([_text_paragraph(1, text)]) == []


def test_a_compound_of_six_or_more_syllables_is_reported_by_the_word() -> None:
    rows = _scan([_text_paragraph(1, "Die Tapeziertischoberfläche glänzt.")])

    assert [(row["rule"], row["snippet"]) for row in rows] == [("de_long_compound", "Tapeziertischoberfläche")]


def test_a_hyphenated_compound_is_not_reported() -> None:
    assert _rule_ids([_text_paragraph(1, "Die Tapeziertisch-Oberfläche glänzt.")]) == []


def test_one_document_can_raise_several_german_rules_at_once() -> None:
    paragraphs = [
        _text_paragraph(1, "Außerdem kam der Hund. Außerdem lief die Katze zur Tapeziertischoberfläche."),
        _text_paragraph(3, LONG_REAL_SENTENCE),
    ]

    assert sorted(_rule_ids(paragraphs)) == ["de_long_compound", "de_repeated_connector", "de_sentence_length"]
