"""Keep German detection contextual, because lexical recall alone permits false findings."""

import json
import re
from pathlib import Path

import pytest

from lib import german_rules
from lib.german_readability import sentences
from lib.german_rules._text import sentence_hits, sentence_spans
from lib.prose_language import ParagraphLanguage
from lib.german_syllables import count_syllables
from lib.scanner import scan_all


def matrix_cases(kind: str) -> list:
    """Keep adjudicated examples together, because their labels distinguish intended targets."""
    path = Path(__file__).parent / "fixtures" / "german_repair_matrix.json"
    families = json.loads(path.read_text(encoding="utf-8"))
    return [
        pytest.param(rule, text, id=f"{rule}-{index + 1}")
        for rule, examples in families.items()
        for index, text in enumerate(examples[kind])
    ]


def masked_cases() -> list:
    """Mention each lexical family, because quotation must not become the writer's assertion."""
    path = Path(__file__).parent / "fixtures" / "german_repair_matrix.json"
    families = json.loads(path.read_text(encoding="utf-8"))
    return [
        pytest.param(rule, examples["positive"][0], id=rule)
        for rule, examples in families.items()
        if rule != "de_markdown_artifact"
    ]


@pytest.fixture(name="german_config")
def fixture_german_config(tmp_path) -> dict:
    """Isolate scanner roots, because local installations must not affect detector results."""
    return {
        "prose_languages": ["de"],
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
        "reports_dir": str(tmp_path / "reports"),
    }


def rule_rows(text: str, rule: str, config: dict) -> list[dict]:
    """Select the requested finding, because unrelated rules have independent contracts."""
    return [row for row in scan_all("probe.md", text, config) if row["rule"] == rule]


@pytest.mark.parametrize(("rule", "text"), matrix_cases("positive"))
def test_german_matrix_targets_raise_the_selected_rule(rule, text, german_config) -> None:
    assert rule_rows(text, rule, german_config)


@pytest.mark.parametrize(("rule", "text"), matrix_cases("negative"))
def test_german_matrix_controls_do_not_raise_the_selected_rule(rule, text, german_config) -> None:
    assert rule_rows(text, rule, german_config) == []


@pytest.mark.parametrize(("rule", "text"), masked_cases())
@pytest.mark.parametrize("wrapper", ["`{text}`", "Der Test erwähnt „{text}“ als Beispiel."])
def test_mentioned_german_phrase_families_do_not_become_assertions(
    rule, text, wrapper, german_config
) -> None:
    assert rule_rows(wrapper.format(text=text), rule, german_config) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Am 3. Mai 2026 fand die Sitzung statt.", ["Am 3. Mai 2026 fand die Sitzung statt."]),
        (
            "Am 3. Mai 2026 fand die Sitzung statt. Danach gingen wir.",
            ["Am 3. Mai 2026 fand die Sitzung statt.", "Danach gingen wir."],
        ),
    ],
)
def test_german_readability_keeps_month_ordinals_inside_sentences(text, expected) -> None:
    assert sentences(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Am 3. Mai 2026 fand die Sitzung statt.", [(0, "Am 3. Mai 2026 fand die Sitzung statt.")]),
        (
            "Am 3. Mai 2026 fand die Sitzung statt. Danach gingen wir.",
            [(0, "Am 3. Mai 2026 fand die Sitzung statt."), (39, "Danach gingen wir.")],
        ),
    ],
)
def test_german_sentence_spans_preserve_offsets_after_month_ordinals(text, expected) -> None:
    assert sentence_spans(text) == expected


def test_document_rhythm_counts_ordinal_date_sentences_as_whole(german_config) -> None:
    text = " ".join(["Am 3. Mai 2026 fand die Sitzung statt."] * 8)
    rows = rule_rows(text, "de_uniform_rhythm", german_config)
    assert [row["line"] for row in rows] == [1]


@pytest.mark.parametrize(
    ("word", "expected"),
    [("Mai", 1), ("Kaiser", 2), ("naiv", 2), ("Naivität", 4), ("Mosaik", 3),
     ("Kokain", 3), ("Theater", 3), ("Qualität", 3)],
)
def test_german_syllables_distinguish_diphthongs_from_loanword_hiatus(word, expected) -> None:
    assert count_syllables(word) == expected


@pytest.mark.parametrize(
    ("text", "expected_lines"),
    [
        ("Z. B. gilt die Regel ab 3. Mai 2026. D. h. die Prüfung läuft weiter.", []),
        ("Wir liefern usw. alle Teile, bzw. die noch fehlenden Stücke, d.h. bis Freitag.", [1]),
    ],
)
def test_explanatory_abbreviations_need_a_completed_clause(text, expected_lines, german_config) -> None:
    rows = rule_rows(text, "de_unexplained_abbreviation", german_config)
    assert sorted({row["line"] for row in rows}) == expected_lines


@pytest.mark.parametrize(
    "text",
    ["Der Client nimmt eine Prüfung des Tokens vor.",
     "Der Handler führte eine Validierung der Eingabe durch."],
)
def test_inflected_stretched_verbs_report_the_actual_physical_line(text, german_config) -> None:
    rows = rule_rows(
        "Der Dienst startet.\nDer Client wartet.\n" + text,
        "de_stretched_verb",
        german_config,
    )
    assert [row["line"] for row in rows] == [3]


def test_two_filler_matches_survive_in_one_sentence(german_config) -> None:
    rows = rule_rows("Das ist eigentlich irgendwie gut.", "de_filler_word", german_config)
    assert [(row["line"], row["match"]) for row in rows] == [
        (1, "eigentlich"), (1, "irgendwie")
    ]


@pytest.mark.parametrize(
    ("text", "expected_matches"),
    [
        (
            "Der Cache ist völlig leer; keys gibt 0 zurück, aber die Lösung ist unglaublich robust.",
            ["unglaublich"],
        ),
        ("Python 3.13 ist unglaublich robust.", ["unglaublich"]),
        ("Der Server ist absolut erreichbar: Der Healthcheck liefert HTTP 200.", []),
    ],
)
def test_quantitative_evidence_clears_only_its_own_claim(text, expected_matches, german_config) -> None:
    rows = rule_rows(text, "de_empty_intensifier", german_config)
    assert [row["match"] for row in rows] == expected_matches


def test_literal_evidence_does_not_hide_a_later_symbolic_claim(german_config) -> None:
    rows = rule_rows(
        "Der Bericht ist ein Beweis für den Erfolg und spielt eine wichtige Rolle im Produkt.",
        "de_symbolism_inflation",
        german_config,
    )
    assert [(row["line"], row["match"]) for row in rows] == [(1, "spielt eine wichtige Rolle")]


@pytest.mark.parametrize(("value", "expected_lines"), [(12, [1]), (13, [])])
def test_summary_context_distinguishes_repetition_from_new_facts(value, expected_lines, german_config) -> None:
    rows = rule_rows(
        f"Die Latenz beträgt 12 ms. Zusammenfassend beträgt die Latenz {value} ms.",
        "de_section_summary",
        german_config,
    )
    assert [row["line"] for row in rows] == expected_lines


@pytest.mark.parametrize(
    ("text", "expected_line"),
    [("## Einrichtung\nText.\n#### Voraussetzungen", 3), ("Text.\n---\n## Status", 2)],
)
def test_german_markdown_findings_use_physical_lines(text, expected_line, german_config) -> None:
    rows = rule_rows(text, "de_markdown_artifact", german_config)
    assert [row["line"] for row in rows] == [expected_line]


@pytest.mark.parametrize(
    ("text", "rule", "expected_lines"),
    [
        ("Marias Konfiguration liegt im Ordner.", "genitive_apostrophe", []),
        ("Der Bericht zitiert „Maria's configuration“ als englischen Titel.", "genitive_apostrophe", []),
        ("Er sagte: „Warte... ich komme“.", "typed_ellipsis", []),
        ("Die Antwort lautet... später.", "typed_ellipsis", [1]),
        ("Er sagte: „Warte… ich komme“.", "typed_ellipsis", []),
        ("Das Literal `...` steht im Test.", "typed_ellipsis", []),
    ],
)
def test_german_punctuation_applies_inside_prose_but_preserves_literals(
    text, rule, expected_lines, german_config
) -> None:
    rows = rule_rows(text, rule, german_config)
    assert sorted({row["line"] for row in rows}) == expected_lines


@pytest.mark.parametrize(
    ("text", "expected_match"),
    [
        pytest.param("Marias's Konfiguration wurde überschrieben.", "Marias's", id="repeated-s-opening"),
        pytest.param("Das ist Marias's Konfiguration.", "Marias's", id="repeated-s-medial"),
        pytest.param("Peter's Konfiguration wurde überschrieben.", "Peter's", id="opening-name"),
        pytest.param("Das ist Peter's Buch.", "Peter's", id="medial-name"),
        pytest.param("Maria's's Konfiguration wurde überschrieben.", "Maria's's", id="repeated-ending"),
        pytest.param("Maria''s Konfiguration wurde überschrieben.", "Maria''s", id="repeated-apostrophe"),
    ],
)
def test_malformed_german_genitives_report_the_entire_name(
    text, expected_match, german_config
) -> None:
    rows = rule_rows(text, "genitive_apostrophe", german_config)
    assert [(row["line"], row["match"]) for row in rows] == [(1, expected_match)]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Hans' Konfiguration wurde überschrieben.", id="name-ending-in-s"),
        pytest.param("Marias Konfiguration wurde überschrieben.", id="ordinary-genitive"),
        pytest.param(
            "Wie geht's dir heute, weil wir das so wollen und es nicht anders geht.",
            id="elision",
        ),
        pytest.param("Er zitierte: „Peter's configuration is ready“ und ging.", id="quoted-english"),
    ],
)
def test_german_genitive_detection_preserves_names_elisions_and_quoted_english(
    text, german_config
) -> None:
    assert rule_rows(text, "genitive_apostrophe", german_config) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        pytest.param("Eigentlich wollte ich fragen, ob Python 3.13 unterstützt wird.", [], id="intention"),
        pytest.param("Der Dienst antwortet irgendwie anders als dokumentiert.", [], id="comparison"),
        pytest.param("Eigentlich wollte ich halt fragen, ob Python unterstützt wird.", ["halt"], id="other-particle"),
        pytest.param("Eigentlich wollte ich eigentlich fragen, ob Python unterstützt wird.", ["eigentlich"], id="second-particle"),
        pytest.param("Das Team sagt, eigentlich wollte ich fragen, ob Python unterstützt wird.", ["eigentlich"], id="embedded-intention"),
    ],
)
def test_a_meaningful_particle_does_not_hide_other_fillers(text, expected) -> None:
    rows = german_rules.check_paragraphs(
        "doc.md", [ParagraphLanguage(line=1, text=text, language="de", weak=False)]
    )

    assert [(row["match"], row["line"]) for row in rows if row["rule"] == "de_filler_word"] == [
        (word, 1) for word in expected
    ]


def test_sentence_filter_retains_each_unsuppressed_physical_line() -> None:
    paragraph = ParagraphLanguage(line=5, text="halt\nhalt irgendwie.", language="de", weak=False)
    hits = sentence_hits(
        "de_filler_word", [paragraph], re.compile(r"\b(?:halt|irgendwie)\b"),
        unless=lambda _sentence, match: match.group() == "irgendwie",
    )

    assert [(hit.line, hit.match) for hit in hits] == [(5, "halt"), (6, "halt")]
