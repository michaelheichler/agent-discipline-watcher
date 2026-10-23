"""Because a syllable count flags loanwords and code, a long word counts as a compound only when it splits into real German parts."""
from __future__ import annotations

import re

import pytest

from lib.config import resolve_outcome
from lib.findings import Outcome
from lib.scanner import scan_all

GERMAN_ONLY = {"prose_languages": ["de"]}
COMPOUND_RULES = frozenset({"de_long_compound", "de_compound_hint"})
PLAIN_COMPOUND_LINE = "Die Außentemperatur sinkt heute."


def _compound_rows(text: str) -> list[dict]:
    return [row for row in scan_all("doc.md", text, GERMAN_ONLY) if row["rule"] in COMPOUND_RULES]


def _lines(text: str) -> list[int]:
    return [row["line"] for row in _compound_rows(text)]


def _words_in(row: dict) -> set[str]:
    reader_text = " ".join(value for value in row.values() if isinstance(value, str))
    return set(re.findall(r"\w+", reader_text.lower()))


@pytest.mark.parametrize("word", ("Außentemperatur", "Temperaturquellen", "Bedienelemente", "Tapeziertischoberfläche"))
def test_a_word_built_from_german_parts_is_flagged(word: str) -> None:
    assert _lines(f"Der Bericht nennt die {word} für heute.\n") == [1]


@pytest.mark.parametrize("word", (
    "Informationen", "Automationen", "Dokumentation", "Entscheidungen",
    "Konstruktionen", "Internationale", "möglicherweise", "unterschiedlich",
))
def test_a_long_word_that_does_not_split_into_german_parts_is_not_flagged(word: str) -> None:
    assert _lines(f"Der Bericht nennt {word} für heute.\n") == []


@pytest.mark.parametrize("masked_line", (
    pytest.param("Der Wert liegt in `sessionStorage` bereit.", id="inline-code"),
    pytest.param("Der Wert liegt in `Datenbankverbindung` bereit.", id="inline-code-compound"),
    pytest.param('Der Status zeigt "Unavailable" an.', id="quoted"),
    pytest.param('Der Status zeigt "Datenbankverbindung" an.', id="quoted-compound"),
    pytest.param("Die Anleitung steht unter https://example.org/wiki/Datenbankverbindung bereit.", id="url"),
    pytest.param("Die Anleitung steht in docs/Datenbankverbindung.md bereit.", id="path"),
    pytest.param("Der Schalter datenbankVerbindung bleibt aus.", id="camel-case"),
    pytest.param("Der Schalter Datenbankverbindung2 bleibt aus.", id="digit-token"),
))
def test_a_masked_token_is_never_flagged_while_the_plain_compound_beside_it_is(masked_line: str) -> None:
    assert _lines(f"{masked_line}\n{PLAIN_COMPOUND_LINE}\n") == [2]


@pytest.mark.parametrize(("sentence", "rule", "outcome"), (
    pytest.param(
        "Die Donaudampfschifffahrtsgesellschaft fährt heute.", "de_long_compound", Outcome.BLOCK,
        id="past-the-block-bar-blocks",
    ),
    pytest.param(
        "Die Datenbankverbindung bricht heute ab.", "de_compound_hint", Outcome.WOULD_BLOCK,
        id="under-the-block-bar-is-advice",
    ),
))
def test_the_word_length_decides_whether_a_compound_blocks_or_advises(sentence: str, rule: str, outcome: Outcome) -> None:
    rows = _compound_rows(sentence + "\n")

    assert [(row["rule"], resolve_outcome(row, GERMAN_ONLY)) for row in rows] == [(rule, outcome)]


def test_the_finding_names_each_part_of_the_split() -> None:
    rows = _compound_rows(PLAIN_COMPOUND_LINE + "\n")

    assert {"außen", "temperatur"} <= _words_in(rows[0])


def test_a_compound_is_reported_by_its_word_on_its_own_line() -> None:
    rows = _compound_rows("Der Bericht kam gestern an.\nEr nennt die Tapeziertischoberfläche.\n")

    assert [(row["line"], row["match"]) for row in rows] == [(2, "Tapeziertischoberfläche")]


def test_a_compound_the_writer_already_hyphenated_is_not_flagged() -> None:
    assert _lines("Die Tapeziertisch-Oberfläche glänzt.\n") == []


@pytest.mark.parametrize("sentence", (
    pytest.param("Die amerikanischen Kunden zahlen heute.", id="amerikanischen"),
    pytest.param("Die brasilianische Firma zahlt heute.", id="brasilianische"),
    pytest.param("Die südkoreanischen Kunden zahlen heute.", id="suedkoreanischen"),
))
def test_an_adjective_ending_in_anisch_is_not_read_as_a_nische_compound(sentence: str) -> None:
    assert _lines(sentence + "\n") == []


@pytest.mark.parametrize("sentence", (
    pytest.param("Die Badezimmernische bleibt heute frei.", id="badezimmernische"),
    pytest.param("Die Schlafzimmernischen bleiben heute frei.", id="schlafzimmernischen"),
))
def test_a_nische_compound_after_a_consonant_is_still_flagged(sentence: str) -> None:
    assert _lines(sentence + "\n") == [1]


def test_a_compound_ending_in_an_anisch_adjective_names_its_real_parts() -> None:
    rows = _compound_rows("Die nordamerikanische Firma zahlt heute.\n")

    assert len(rows) == 1
    assert {"nord", "amerikanische"} <= _words_in(rows[0])
