"""Because a table cell is not a paragraph, German sentence rules must read each cell alone and keep reading the prose around the table."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

GERMAN_ONLY = {"prose_languages": ["de"]}
TABLE_HEAD = "| Bereich | Stand |\n| --- | --- |\n"
UNFINISHED_ROW = "| Lager | Die Stadt liegt am Fluss. Die Gründung der Stadt war |\n"


def _lines(text: str, rule: str) -> list[int]:
    return [row["line"] for row in scan_all("doc.md", text, GERMAN_ONLY) if row["rule"] == rule]


@pytest.mark.parametrize("text", (
    pytest.param(
        "Bereich | Stand\n--- | ---\nVertrieb | Läuft gut.\nLager | Umbau läuft\n",
        id="table-without-outer-pipes",
    ),
    pytest.param(
        "Die Werte stehen hier. Sie gelten ab Montag.\n| Bereich | Stand\n| --- | ---\n| Lager | Umbau läuft\n",
        id="prose-directly-above-rows-without-trailing-pipe",
    ),
))
def test_a_table_closing_the_document_is_not_an_abrupt_ending(text: str) -> None:
    assert _lines(text, "de_abrupt_ending") == []


def test_a_closing_phrase_ending_a_middle_table_cell_is_flagged_on_its_row() -> None:
    text = (
        "| Bereich | Stand |\n| --- | --- |\n"
        "| Vertrieb | Wir sind bestens aufgestellt |\n"
        "| Lager | Der Umbau läuft. Das Dach folgt im Mai. |\n"
    )

    assert _lines(text, "de_corporate_closing") == [3]


def test_an_unfinished_last_prose_paragraph_after_a_table_still_ends_abruptly() -> None:
    text = "Bereich | Stand\n--- | ---\nLager | Umbau läuft\n\nDie Stadt liegt am Fluss. Die Gründung der Stadt war\n"

    assert _lines(text, "de_abrupt_ending") == [5]


def test_a_closing_phrase_on_prose_directly_above_a_table_is_still_flagged() -> None:
    text = (
        "Der Umsatz stieg um vier Prozent. Die Firma ist bestens aufgestellt.\n"
        "| Bereich | Stand\n| --- | ---\n| Lager | Umbau läuft\n"
    )

    assert _lines(text, "de_corporate_closing") == [1]


@pytest.mark.parametrize("text", (
    pytest.param(TABLE_HEAD + UNFINISHED_ROW, id="last-row"),
    pytest.param(TABLE_HEAD + UNFINISHED_ROW + "| Firma | Der Umbau läuft. |\n", id="middle-row"),
))
def test_an_unfinished_table_cell_ends_abruptly_on_its_own_row(text: str) -> None:
    assert _lines(text, "de_abrupt_ending") == [3]


def test_exclamations_in_separate_cells_do_not_form_a_staccato_run() -> None:
    text = TABLE_HEAD + "| Das klappt! | Es läuft! |\n| Alles gut! | Wir kommen! |\n"

    assert _lines(text, "de_exclamation_staccato") == []


def test_an_exclamation_run_inside_one_cell_is_flagged_on_its_row() -> None:
    text = TABLE_HEAD + "| Lager | Das klappt! Es läuft! Alles gut! |\n"

    assert _lines(text, "de_exclamation_staccato") == [3]
