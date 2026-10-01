"""Each humanizer-de phrase rule fires on its bad example and stays quiet on its good one, because a rule that fires on clean text trains writers to ignore it."""
from __future__ import annotations

import pytest

from lib import german_rules
from lib.prose_language import ParagraphLanguage

VIOLATING = [
    ("de_symbolism_inflation", "Die Kathedrale steht als Zeugnis für die Kunst des Mittelalters."),
    ("de_meta_commentary", "Es ist wichtig zu bemerken, dass die Bevölkerung gewachsen ist."),
    ("de_section_summary", "Die Region hat drei Universitäten. Insgesamt verfügt die Stadt über gute Infrastruktur."),
    ("de_ai_marker_vocabulary", "Der Artikel beleuchtet das vielschichtige Zusammenspiel der Akteure."),
    ("de_corporate_closing", "Der Umsatz stieg um vier Prozent. Mit dieser Strategie ist die Firma bestens aufgestellt."),
    ("de_letter_frame", "Betreff: Neuer Abschnitt\nDer Hook prüft jede Datei vor dem Schreiben."),
    ("de_chatbot_talk", "Der Hook läuft vor jedem Schreiben. Ich hoffe, das hilft dir weiter."),
    ("de_chatbot_talk", "Gute Frage! Der Hook läuft vor jedem Schreiben."),
    ("de_knowledge_cutoff", "Bis zu meinem letzten Update gab es kein neues Release."),
    ("de_prompt_refusal", "Als KI-Sprachmodell kann ich das nicht beurteilen."),
    ("de_therapeutic_validation", "Du bist nicht zu sensibel. Du wurdest nur zu lange nicht ernst genommen."),
]

CLEAN = [
    ("de_symbolism_inflation", "ADW steht für Agent Discipline Watcher."),
    ("de_meta_commentary", "Die Bevölkerung wuchs in diesem Zeitraum."),
    ("de_section_summary", "Insgesamt laufen 40 Tests in der Suite."),
    ("de_section_summary", "Abschließend startest du den Server neu."),
    ("de_ai_marker_vocabulary", "Der Artikel beschreibt das Zusammenspiel der Akteure."),
    ("de_corporate_closing", "Die Firma ist bestens aufgestellt. Der Umsatz stieg um vier Prozent."),
    ("de_letter_frame", "Vielen Dank für den Hinweis auf den Fehler im Hook."),
    ("de_chatbot_talk", "Das ist eine gute Frage für das nächste Treffen."),
    ("de_knowledge_cutoff", "Stand: 1. Oktober 2026. Der Hook prüft jede Datei."),
    ("de_prompt_refusal", "Wir setzen Claude als KI-Modell für die Prüfung ein."),
    ("de_therapeutic_validation", "Es liegt nicht an dir. Der Server weist derzeit alle Konten ab."),
]


def _paragraph(text: str) -> ParagraphLanguage:
    return ParagraphLanguage(line=1, text=text, language="de", weak=False)


def _fired(text: str) -> set[str]:
    return {row["rule"] for row in german_rules.check_paragraphs("doc.md", [_paragraph(text)])}


@pytest.mark.parametrize(("rule", "text"), VIOLATING)
def test_the_bad_example_raises_its_rule(rule: str, text: str) -> None:
    assert rule in _fired(text)


@pytest.mark.parametrize(("rule", "text"), CLEAN)
def test_the_good_example_stays_quiet(rule: str, text: str) -> None:
    assert rule not in _fired(text)


def test_ai_markers_count_across_the_whole_text() -> None:
    paragraphs = [_paragraph("Der Bericht beleuchtet den Markt."), _paragraph("Die Lage ist spannend und dynamisch.")]

    rows = german_rules.check_paragraphs("doc.md", paragraphs)

    assert [row["match"] for row in rows if row["rule"] == "de_ai_marker_vocabulary"] == [
        "beleuchtet", "spannend", "dynamisch",
    ]


def test_a_quoted_refusal_is_not_the_writers_own_voice() -> None:
    assert "de_prompt_refusal" not in _fired("Der Bot schrieb „Als KI-Sprachmodell kann ich das nicht“ ins Log.")
