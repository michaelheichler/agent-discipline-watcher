"""Protect the German semantic path, because a German row judged against English exemplars or an English rubric measures nothing."""
from __future__ import annotations

import pytest

from lib import embedding_session, german_rules, pattern_semantic
from lib.judge_contracts import GERMAN_PATTERN_RUBRIC, PATTERN_RUBRIC, build_prompt
from lib.pattern_judge import PatternCandidate, request_for
from lib.pattern_semantic import Exemplar, Layer

ENGLISH_SENTENCE = "Let me know if you need anything else today."
GERMAN_SENTENCE = "Die Gebühren für das Schwimmbad werden von der Stadt im nächsten Jahr wieder erhöht."
DOCUMENT = f"{ENGLISH_SENTENCE} The team will be glad to help you with it.\n\n{GERMAN_SENTENCE}\n"
NEAR_VIOLATING = (1.0, 0.0)
NEAR_CLEAN = (0.0, 1.0)
BOTH_SIDES = (
    Exemplar("ai_closer", "violating", "I hope this helps with your project."),
    Exemplar("ai_closer", "clean", "The cache holds 4096 entries."),
    Exemplar("de_example", "violating", "Die Straße wird gesperrt."),
    Exemplar("de_example", "clean", "Die Stadt sperrt die Straße."),
)
MANIFEST = {
    "rules": {
        "ai_closer": {"action": "End when the answer is done.", "judge_precision": 1.0},
        "de_example": {"action": "Nenn den Handelnden.", "judge_precision": 1.0, "language": "de"},
    }
}


def _vector(text: str) -> tuple[float, float]:
    return NEAR_CLEAN if text in {"The cache holds 4096 entries.", "Die Stadt sperrt die Straße."} else NEAR_VIOLATING


def _vectors(texts, *_config) -> dict:
    return {text: _vector(text) for text in texts}


def _layer(exemplars: tuple[Exemplar, ...]) -> Layer:
    return Layer(
        exemplars=lambda: exemplars,
        manifest=lambda: MANIFEST,
        exemplar_vectors=lambda rows, *_config: _vectors({row.text for row in rows}),
        vectors=_vectors,
    )


@pytest.fixture(name="opted_in")
def _opted_in(monkeypatch) -> None:
    monkeypatch.delenv(embedding_session.DISABLE_ENV, raising=False)
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")


def _voted_texts(found: dict, rule: str) -> set[str]:
    return {candidate.text for candidate in found.get(rule, ())}


@pytest.mark.usefixtures("opted_in")
def test_a_german_rule_votes_only_on_german_sentences() -> None:
    found = pattern_semantic.candidates("notes.md", DOCUMENT, {}, layer=_layer(BOTH_SIDES))

    assert _voted_texts(found, "de_example") == {GERMAN_SENTENCE}


@pytest.mark.usefixtures("opted_in")
def test_an_english_rule_no_longer_votes_on_german_sentences() -> None:
    found = pattern_semantic.candidates("notes.md", DOCUMENT, {}, layer=_layer(BOTH_SIDES))

    assert GERMAN_SENTENCE not in _voted_texts(found, "ai_closer")
    assert ENGLISH_SENTENCE in _voted_texts(found, "ai_closer")


@pytest.mark.usefixtures("opted_in")
def test_a_rule_without_violating_exemplars_never_fires() -> None:
    clean_only = tuple(row for row in BOTH_SIDES if not (row.rule == "de_example" and row.label == "violating"))

    found = pattern_semantic.candidates("notes.md", DOCUMENT, {}, layer=_layer(clean_only))

    assert "de_example" not in found


@pytest.mark.usefixtures("opted_in")
def test_an_english_project_setting_keeps_german_rules_silent() -> None:
    found = pattern_semantic.candidates("notes.md", DOCUMENT, {"prose_languages": ["en"]}, layer=_layer(BOTH_SIDES))

    assert "de_example" not in found


def test_a_german_row_reaches_the_judge_with_the_german_rubric() -> None:
    rule = pattern_semantic.rule_prompt("de_example", BOTH_SIDES, MANIFEST)

    prompt = build_prompt(request_for(rule, (PatternCandidate("notes.md", 3, GERMAN_SENTENCE),)))

    assert GERMAN_PATTERN_RUBRIC in prompt
    assert PATTERN_RUBRIC not in prompt
    assert "Die Stadt sperrt die Straße." in prompt


def test_an_english_row_keeps_the_english_rubric() -> None:
    rule = pattern_semantic.rule_prompt("ai_closer", BOTH_SIDES, MANIFEST)

    prompt = build_prompt(request_for(rule, (PatternCandidate("notes.md", 1, ENGLISH_SENTENCE),)))

    assert PATTERN_RUBRIC in prompt
    assert GERMAN_PATTERN_RUBRIC not in prompt


def test_a_german_prompt_with_no_violating_side_shows_no_empty_violating_line() -> None:
    clean_only = tuple(row for row in BOTH_SIDES if row.label == "clean")
    rule = pattern_semantic.rule_prompt("de_example", clean_only, MANIFEST)

    prompt = build_prompt(request_for(rule, (PatternCandidate("notes.md", 3, GERMAN_SENTENCE),)))

    assert "violating:" not in prompt


@pytest.mark.parametrize("rule", german_rules.voted(), ids=lambda rule: rule.name)
def test_every_german_semantic_rule_ships_a_clean_side_and_its_german_fix(rule: german_rules.Rule) -> None:
    prompt = pattern_semantic.rule_prompt(rule.name, pattern_semantic.load_exemplars(), pattern_semantic.load_manifest())

    assert prompt.action == rule.german.action
    assert len(prompt.clean_examples) == pattern_semantic.JUDGE_EXAMPLES


@pytest.mark.parametrize("rule", german_rules.voted(), ids=lambda rule: rule.name)
def test_no_german_semantic_rule_speaks_before_it_is_measured(rule: german_rules.Rule) -> None:
    assert rule.name not in pattern_semantic.measured_rules(pattern_semantic.load_manifest())
