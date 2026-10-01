"""Each German STATIC rule fires on its bad example and stays quiet on its good one, because a rule that fires on clean text trains writers to ignore it."""
from __future__ import annotations

import pytest

from lib import german_rules
from lib.prose_language import ParagraphLanguage
from lib.scanner import scan_all

VIOLATING = [
    ("de_filler_word", "Das müssen wir eigentlich irgendwie anders anpacken."),
    ("de_filler_word", "Was ist denn hier los?"),
    ("de_empty_intensifier", "Das Angebot ist absolut ausreichend für unsere Zwecke."),
    ("de_redundant_pair", "Der telefonische Anruf kam am Morgen."),
    ("de_stretched_verb", "Einige Kollegen stellen diese Technik in Frage."),
    ("de_stretched_verb", "Die Galerie fungiert als Ausstellungsraum und verfügt über vier Räume."),
    ("de_anglicism", "Am Ende des Tages erkannte das Team den Fehler."),
    ("de_abstract_nouns", "Wir prüfen Maßnahmen, Lösungen und Prozesse."),
    ("de_noun_style", "Der Versand der Ware erfolgt am Tag der Bestellung."),
    ("de_modal_verb", "Wir möchten dich auf unser neues Produkt hinweisen."),
    ("de_double_negation", "Schalte die Maschine nicht ein, wenn die Temperatur nicht gesunken ist."),
    ("de_stacked_conditions", "Wenn das Argument stimmt und wenn die Evidenz es stützt, wirkt die Politik."),
]

CLEAN = [
    ("de_filler_word", "Wir müssen das anders anpacken."),
    ("de_filler_word", "Ich bleibe zu Hause, denn es regnet."),
    ("de_empty_intensifier", "Das Angebot reicht für unsere Zwecke."),
    ("de_redundant_pair", "Der Anruf kam am Morgen."),
    ("de_stretched_verb", "Einige Kollegen bezweifeln diese Technik."),
    ("de_stretched_verb", "Die Tür dient als Notausgang."),
    ("de_anglicism", "Schließlich erkannte das Team den Fehler."),
    ("de_abstract_nouns", "Wir prüfen zwei Maßnahmen und eine Lösung."),
    ("de_noun_style", "Wir versenden die Ware am Tag der Bestellung."),
    ("de_modal_verb", "Unser neues Produkt spart dir Zeit."),
    ("de_modal_verb", "Darf ich dich um Geduld bitten?"),
    ("de_double_negation", "Schalte die Maschine erst ein, wenn die Temperatur gesunken ist."),
    ("de_double_negation", "Unser Unternehmen arbeitet nicht am Sonntag."),
    ("de_stacked_conditions", "Wenn das Argument stimmt, wirkt die Politik."),
]


def _paragraph(text: str, line: int = 1) -> ParagraphLanguage:
    return ParagraphLanguage(line=line, text=text, language="de", weak=False)


def _fired(text: str) -> set[str]:
    return {row["rule"] for row in german_rules.check_paragraphs("doc.md", [_paragraph(text)])}


@pytest.mark.parametrize(("rule", "text"), VIOLATING)
def test_the_bad_example_raises_its_rule(rule: str, text: str) -> None:
    assert rule in _fired(text)


@pytest.mark.parametrize(("rule", "text"), CLEAN)
def test_the_good_example_stays_quiet(rule: str, text: str) -> None:
    assert rule not in _fired(text)


def test_a_hit_reports_the_line_its_sentence_sits_on() -> None:
    paragraph = _paragraph("Die erste Zeile passt.\nDas ist eigentlich gut.", line=5)

    rows = german_rules.check_paragraphs("doc.md", [paragraph])

    assert [(row["rule"], row["line"], row["match"], row["snippet"]) for row in rows] == [
        ("de_filler_word", 6, "eigentlich", "Das ist eigentlich gut."),
    ]


def test_a_quoted_phrase_is_not_the_writers_own_style() -> None:
    assert _fired("Sie schrieb „das ist eigentlich gut“ in den Bericht.") == set()


def test_the_scanner_runs_the_german_rules_on_german_paragraphs_only() -> None:
    german = "Das müssen wir eigentlich anders anpacken, weil der Plan nicht zu den Zahlen passt."
    english = "We should eigentlich change the plan, because the numbers do not match the goal."

    rows = scan_all("doc.md", german + "\n\n" + english + "\n")

    assert [(row["rule"], row["line"], row["language"]) for row in rows if row["rule"] == "de_filler_word"] == [
        ("de_filler_word", 1, "de"),
    ]
