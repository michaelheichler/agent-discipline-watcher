"""Because table cells and numbered lists would otherwise pile short sentences into one false hit, each sentence is judged alone."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

GERMAN_ONLY = {"prose_languages": ["de"]}
DENSE_SENTENCE = "Der Kunde bestellt 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 und 11."
EIGHT_NOUNS = "Der Kunde bestellt Brot, Milch, Käse, Wurst, Eier, Butter, Mehl, Zucker"
EIGHT_NOUNS_ASKED = "Bestellt der Kunde Brot, Milch, Käse, Wurst, Eier, Butter, Mehl, Zucker"
NINE_NOUNS = f"{EIGHT_NOUNS} und Saft."
TABLE_HEAD = "| Bereich | Stand |\n| --- | --- |\n"


def _lines(text: str) -> list[int]:
    return [row["line"] for row in scan_all("doc.md", text, GERMAN_ONLY) if row["rule"] == "de_information_cluster"]


def test_short_sentences_in_separate_table_rows_do_not_merge_into_a_cluster() -> None:
    text = (
        "| Bestellung |\n| --- |\n"
        "| Der Kunde bestellt 1, 2 und 3. |\n"
        "| Der Kunde bestellt 4, 5 und 6. |\n"
        "| Der Kunde bestellt 7, 8 und 9. |\n"
    )

    assert _lines(text) == []


def test_short_sentences_in_separate_cells_of_one_row_do_not_merge_into_a_cluster() -> None:
    text = (
        "| Montag | Dienstag | Mittwoch |\n| --- | --- | --- |\n"
        "| Er kauft 1, 2 und 3. | Sie kauft 4, 5 und 6. | Er kauft 7, 8 und 9. |\n"
    )

    assert _lines(text) == []


def test_a_dense_sentence_inside_one_table_cell_still_flags() -> None:
    text = f"| Montag | Dienstag |\n| --- | --- |\n| Der Kunde zahlt bar. | {DENSE_SENTENCE} |\n"

    assert len(_lines(text)) == 1


def test_a_dense_table_cell_reports_the_line_of_its_own_row() -> None:
    text = (
        "| Bestellung |\n| --- |\n"
        "| Der Kunde kauft heute ein. |\n"
        f"| {DENSE_SENTENCE} |\n"
        "| Der Kunde zahlt bar. |\n"
    )

    assert _lines(text) == [4]


def test_six_numbered_items_count_once_each_and_stay_under_the_cap() -> None:
    assert _lines("Der Kunde bestellt die Artikel 1, 2, 3, 4, 5 und 6.\n") == []


@pytest.mark.parametrize("sentence", (
    pytest.param("Der Kunde bestellt die Artikel 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 und 11.", id="numbers"),
    pytest.param("Der Kunde bestellt Brot, Milch, Käse, Wurst, Eier, Butter, Mehl, Zucker, Salz, Honig und Saft.", id="nouns"),
))
def test_a_sentence_with_more_items_than_the_cap_still_flags(sentence: str) -> None:
    assert _lines(sentence + "\n") == [1]


@pytest.mark.parametrize("sentence", (
    pytest.param(f"{EIGHT_NOUNS} und Saft.", id="und"),
    pytest.param(f"{EIGHT_NOUNS} oder Saft.", id="oder"),
    pytest.param(f"{EIGHT_NOUNS} und Kaffee schwarz.", id="adjective-after-the-noun"),
    pytest.param(f"{EIGHT_NOUNS} und Vanillecreme hausgemacht.", id="participle-after-the-noun"),
    pytest.param(f"{EIGHT_NOUNS} und frische Brötchen.", id="adjective-before-the-noun"),
    pytest.param(f"{EIGHT_NOUNS} und Brot vom Bäcker.", id="prepositional-phrase-after-the-noun"),
    pytest.param(f"{EIGHT_NOUNS_ASKED} oder Saft?", id="question"),
    pytest.param(
        "Der Fahrer muss laden, fahren, tanken, parken, liefern, kassieren, zählen, buchen und warten.",
        id="bare-infinitives",
    ),
    pytest.param(
        "Wir wollen kaufen, kochen, backen, braten, dünsten, dämpfen, grillen, rösten und frisch servieren.",
        id="modified-infinitive-last",
    ),
    pytest.param(f"{EIGHT_NOUNS} und frischen Saft.", id="inflected-adjective-before-the-noun"),
    pytest.param(f"{EIGHT_NOUNS} und bestimmte Artikel.", id="determiner-adjective-before-the-noun"),
    pytest.param(
        "Die Übersicht nennt Arbeit, Urlaub, Freizeit, Familie, Gesundheit, Wohnen, Bildung, Kultur und besuchte Orte.",
        id="participle-before-the-noun",
    ),
))
def test_the_last_list_item_after_und_or_oder_counts_as_an_item(sentence: str) -> None:
    assert _lines(sentence + "\n") == [1]


@pytest.mark.parametrize("sentence", (
    pytest.param(f"{EIGHT_NOUNS} und der Fahrer liefert alles am Montag.", id="und-subject-first"),
    pytest.param(f"{EIGHT_NOUNS} oder der Fahrer liefert alles am Montag.", id="oder-subject-first"),
    pytest.param(f"{EIGHT_NOUNS} und heute kommt der Fahrer.", id="und-verb-before-subject"),
    pytest.param(f"{EIGHT_NOUNS} oder morgen kommt der Fahrer.", id="oder-verb-before-subject"),
    pytest.param(f"{EIGHT_NOUNS} und Peter kommt.", id="name-then-present-verb"),
    pytest.param(f"{EIGHT_NOUNS} und Peter kam.", id="name-then-past-verb"),
    pytest.param(f"{EIGHT_NOUNS} und Peter telefoniert.", id="name-then-verb-ending-in-t"),
    pytest.param(f"{EIGHT_NOUNS_ASKED} oder kommt der Fahrer heute?", id="question-verb-first"),
    pytest.param(f"{EIGHT_NOUNS_ASKED} oder muss der Fahrer warten?", id="question-modal-first"),
    pytest.param(f"{EIGHT_NOUNS_ASKED} oder kommt Peter heute?", id="question-verb-then-name"),
))
def test_a_conjunction_that_opens_a_new_clause_adds_no_list_item(sentence: str) -> None:
    assert _lines(sentence + "\n") == []


def test_clauses_joined_by_a_bare_und_beside_a_short_list_stay_clean() -> None:
    sentence = "Der Kunde bestellt Brot, Milch und Käse und der Fahrer liefert alles am Montag.\n"

    assert _lines(sentence) == []


@pytest.mark.parametrize("conjunction", ("und", "oder"))
def test_items_joined_only_by_a_repeated_conjunction_are_not_counted_as_a_list(conjunction: str) -> None:
    items = ["Brot", "Milch", "Käse", "Wurst", "Eier", "Butter", "Mehl", "Zucker", "Salz", "Saft"]
    sentence = "Der Kunde bestellt " + f" {conjunction} ".join(items) + ".\n"

    assert _lines(sentence) == []


@pytest.mark.parametrize("text", (
    pytest.param(f"{TABLE_HEAD}| Lager | Der Code ist `1, 2, 3, 4, 5, 6, 7, 8 und 9`. |\n", id="code-in-a-cell"),
    pytest.param(f"{TABLE_HEAD}| Lager | Der Code ist ``x ` 1, 2, 3, 4, 5, 6, 7, 8 und 9``. |\n", id="nested-backticks-in-a-cell"),
    pytest.param("Der Code ist `1, 2, 3, 4, 5, 6, 7, 8 und 9`.\n", id="code-in-prose"),
))
def test_numbers_inside_inline_code_are_not_counted_as_list_items(text: str) -> None:
    assert _lines(text) == []


@pytest.mark.parametrize("text", (
    pytest.param(f"{TABLE_HEAD}| ``code ` x | y`` | {NINE_NOUNS} |\n", id="dense-cell-beside-nested-code"),
    pytest.param(
        f"{TABLE_HEAD}| Lager | Der Kunde bestellt Brot, Milch, Käse, Wurst, Eier, Butter, `x \\| y` Mehl, Zucker und Saft. |\n",
        id="escaped-pipe-inside-a-dense-cell",
    ),
))
def test_a_dense_sentence_beside_inline_code_still_flags_on_its_row(text: str) -> None:
    assert _lines(text) == [3]
