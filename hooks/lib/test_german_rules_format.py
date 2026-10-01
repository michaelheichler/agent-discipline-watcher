"""Each German format and markup rule fires on its bad example and stays quiet on its good one, because a rule that fires on clean Markdown trains writers to ignore it."""
from __future__ import annotations

import pytest

from lib import german_rules
from lib.prose_language import GERMAN, paragraph_languages
from lib.scanner import scan_all

ZERO_WIDTH_SPACE = chr(0x200B)
SOFT_HYPHEN = chr(0x00AD)
EMOJI_PRESENTATION = chr(0xFE0F)

VIOLATING = [
    ("de_placeholder_text", "Bitte schick die Rechnung an [Name einfügen] bis Freitag."),
    ("de_search_link_citation", "Die Zahl stammt aus einer Umfrage (https://www.google.com/search?q=umfrage+2024)."),
    ("de_ai_tool_artifact", "Die Stadt hat rund 50.000 Einwohner contentReference[oaicite:0]{index=0}."),
    ("de_abrupt_ending", "Die Stadt liegt am Fluss. Die Gründung der Stadt war..."),
    ("de_diff_anchored", "Die Plattform wurde jetzt um KI-gestützte Empfehlungen erweitert."),
    ("de_hidden_unicode", "Die Anmeldung" + ZERO_WIDTH_SPACE + " läuft über das Portal."),
    ("de_english_number_format", "Die Inflation lag bei 3.5 Prozent."),
    ("de_english_number_format", "Der Vertrag endet am May 12, 2026."),
    ("de_fake_bullet", "• Der erste Punkt\n• Der zweite Punkt"),
    ("de_emoji_heading", "## 🎓 Bildung und Forschung"),
    ("de_english_title_case", "## Die Zukunft Der Digitalen Transformation Im Mittelstand"),
    ("de_english_title_case", "## Die Neue KI Strategie"),
    ("de_bullet_punctuation", "Vorteile:\n- Schnell.\n- Günstig.\n- Zuverlässig."),
    ("de_markdown_artifact", "| Funktion | Beschreibung |\n| --- | --- |\n| Tempo | Der Dienst antwortet schnell. |"),
    ("de_markdown_artifact", "## Installation\n\n#### Voraussetzungen"),
    ("de_markdown_artifact", "Der Absatz endet hier.\n\n---\n\n## Nächster Abschnitt"),
]

CLEAN = [
    ("de_placeholder_text", "Bitte schick die Rechnung an Frau Weber bis Freitag."),
    ("de_placeholder_text", "Mehr dazu steht [hier](https://example.org/hilfe)."),
    ("de_search_link_citation", "Die Zahl stammt aus der Umfrage des Bundesamts (https://www.destatis.de/umfrage)."),
    ("de_ai_tool_artifact", "Die Stadt hat rund 50.000 Einwohner."),
    ("de_ai_tool_artifact", "Der Exporter entfernt Reste wie `oaicite` aus dem Text."),
    ("de_abrupt_ending", "Die Stadt liegt am Fluss. Die Gründung der Stadt war 1241."),
    ("de_abrupt_ending", "Prüfe die Eingabe vor dem Speichern in der Datenbank"),
    ("de_abrupt_ending", "Die Liste steht im Wiki. Stand: 1. Oktober 2026"),
    ("de_diff_anchored", "Die Plattform empfiehlt passende Inhalte automatisch."),
    ("de_hidden_unicode", "Die Anmeldung läuft über das Portal 👍" + EMOJI_PRESENTATION + "."),
    ("de_english_number_format", "Die Inflation lag bei 3,5 Prozent am 12. Mai 2026."),
    ("de_english_number_format", "Wir nutzen Python 3.11 und rund 15.000 Euro Budget."),
    ("de_fake_bullet", "- Der erste Punkt\n- Der zweite Punkt"),
    ("de_fake_bullet", "Kontakt • Impressum • Datenschutz"),
    ("de_emoji_heading", "## Bildung und Forschung"),
    ("de_english_title_case", "## Die Zukunft der digitalen Transformation im Mittelstand"),
    ("de_english_title_case", "## Teil 2: Die Grundlagen"),
    ("de_bullet_punctuation", "Vorteile:\n- schnell\n- günstig\n- zuverlässig"),
    ("de_bullet_punctuation", "- Starte den Dienst neu.\n- Prüfe danach das Protokoll."),
    ("de_markdown_artifact", "| Funktion | Wert |\n| --- | --- |\n| Tempo | hoch |\n| Last | gering |"),
    ("de_markdown_artifact", "## Installation\n\n### Voraussetzungen"),
    ("de_markdown_artifact", "Der Absatz endet hier.\n\n## Nächster Abschnitt"),
]


def _rows(text: str, path: str = "doc.md") -> list[dict]:
    return german_rules.check_paragraphs(path, paragraph_languages(text, (GERMAN,)))


def _fired(text: str, path: str = "doc.md") -> set[str]:
    return {row["rule"] for row in _rows(text, path)}


@pytest.mark.parametrize(("rule", "text"), VIOLATING)
def test_the_bad_example_raises_its_rule(rule: str, text: str) -> None:
    assert rule in _fired(text)


@pytest.mark.parametrize(("rule", "text"), CLEAN)
def test_the_good_example_stays_quiet(rule: str, text: str) -> None:
    assert rule not in _fired(text)


@pytest.mark.parametrize("path", ["CHANGELOG.md", "commit_message.md", "docs/release-notes.md"])
def test_a_change_story_belongs_in_a_changelog_or_commit(path: str) -> None:
    assert "de_diff_anchored" not in _fired("Die Suche wurde jetzt um Filter erweitert.", path)


def test_a_hidden_character_is_named_by_its_code_point() -> None:
    rows = _rows("Die Anmeldung" + SOFT_HYPHEN + " läuft.")

    assert [row["match"] for row in rows if row["rule"] == "de_hidden_unicode"] == ["U+00AD"]


def test_the_scanner_keeps_markdown_for_the_german_markup_rules() -> None:
    text = "## 🎓 Bildung\n\nDie Hochschule bietet dir viele Kurse an, weil der Bedarf in der Region wächst.\n"

    rows = scan_all("doc.md", text)

    assert [(row["rule"], row["line"]) for row in rows if row["rule"] == "de_emoji_heading"] == [
        ("de_emoji_heading", 1),
    ]
