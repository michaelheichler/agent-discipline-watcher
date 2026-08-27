from __future__ import annotations

import pytest

from lib import pattern_semantic
from lib.pattern_semantic import Exemplar, Sentence

EXEMPLARS = (
    Exemplar("ai_closer", "violating", "Let me know if you need anything else."),
    Exemplar("ai_closer", "violating", "I hope this helps with your project."),
    Exemplar("ai_closer", "clean", "The cache holds 4096 entries."),
    Exemplar("ai_closer", "clean", "The build finished in nine seconds."),
)
VECTORS = {
    "Let me know if you need anything else.": (1.0, 0.0),
    "I hope this helps with your project.": (0.9, 0.1),
    "The cache holds 4096 entries.": (0.0, 1.0),
    "The build finished in nine seconds.": (0.1, 0.9),
    "Feel free to ask me anything else.": (0.95, 0.05),
    "The lease expires after 900 seconds.": (0.05, 0.95),
}


def test_the_shipped_exemplars_carry_both_sides_for_every_rule() -> None:
    exemplars = pattern_semantic.load_exemplars()
    rules = {row.rule for row in exemplars}

    assert rules
    for rule in rules:
        sides = {row.label for row in exemplars if row.rule == rule}
        assert sides == {"violating", "clean"}, rule


def test_every_shipped_rule_carries_an_action_for_the_judge() -> None:
    manifest = pattern_semantic.load_manifest()

    for rule, row in manifest["rules"].items():
        assert row["action"].strip(), rule


def test_an_unmeasured_rule_never_speaks() -> None:
    manifest = {"rules": {"measured": {"judge_precision": 0.94}, "unmeasured": {"judge_precision": None}}}

    assert pattern_semantic.measured_rules(manifest) == ("measured",)


def test_only_a_measured_rule_blocks() -> None:
    manifest = {
        "rules": {
            "measured_high": {"judge_precision": 0.94},
            "measured_low": {"judge_precision": 0.60},
            "unmeasured": {"judge_precision": None},
        }
    }

    assert pattern_semantic.blocking_rules(manifest) == frozenset({"measured_high"})


def test_the_shipped_gate_matches_the_recorded_measurement() -> None:
    manifest = pattern_semantic.load_manifest()
    blocking = pattern_semantic.blocking_rules(manifest)

    assert "ai_closer" in blocking
    for rule in blocking:
        assert manifest["rules"][rule]["judge_precision"] >= pattern_semantic.ENFORCE_PRECISION


def test_a_near_neighbour_of_the_violating_side_becomes_a_candidate() -> None:
    sentences = (Sentence(3, "Feel free to ask me anything else."),)

    found = pattern_semantic.candidates_for("ai_closer", sentences, VECTORS, EXEMPLARS, "a.md")

    assert [item.line for item in found] == [3]


def test_a_near_neighbour_of_the_clean_side_is_not_a_candidate() -> None:
    sentences = (Sentence(4, "The lease expires after 900 seconds."),)

    assert pattern_semantic.candidates_for("ai_closer", sentences, VECTORS, EXEMPLARS, "a.md") == ()


def test_a_sentence_without_a_vector_is_never_flagged() -> None:
    sentences = (Sentence(5, "This sentence was never embedded at all."),)

    assert pattern_semantic.candidates_for("ai_closer", sentences, VECTORS, EXEMPLARS, "a.md") == ()


def test_an_absent_server_yields_no_finding_rather_than_a_clean_verdict(monkeypatch) -> None:
    monkeypatch.setattr(pattern_semantic, "embed", lambda _texts: None)

    assert pattern_semantic.scan("a.md", "The cache was rebuilt overnight by the scheduler.\n") == ()


def test_a_document_without_prose_costs_no_embedding(monkeypatch) -> None:
    monkeypatch.setattr(
        pattern_semantic, "embed", lambda _texts: pytest.fail("embedded a document carrying no prose")
    )

    assert pattern_semantic.scan("a.md", "") == ()


def test_the_layer_is_silent_until_the_reader_opts_in(monkeypatch) -> None:
    monkeypatch.setattr(pattern_semantic, "enabled", lambda: False)
    monkeypatch.setattr(
        pattern_semantic, "_vectors", lambda _texts: pytest.fail("embedded while the layer was switched off")
    )

    assert pattern_semantic.scan("a.md", "Feel free to ask me anything else.\n") == ()


def test_the_judge_decides_which_candidates_become_findings(monkeypatch) -> None:
    monkeypatch.setattr(pattern_semantic, "enabled", lambda: True)
    monkeypatch.setattr(pattern_semantic, "load_exemplars", lambda: EXEMPLARS)
    monkeypatch.setattr(
        pattern_semantic, "load_manifest",
        lambda: {"rules": {"ai_closer": {"action": "End when the answer is done.", "judge_precision": 1.0}}},
    )
    monkeypatch.setattr(pattern_semantic, "exemplar_vectors", lambda _exemplars: VECTORS)
    monkeypatch.setattr(pattern_semantic, "_vectors", lambda _texts: VECTORS)
    monkeypatch.setattr(
        pattern_semantic, "confirm_all",
        lambda work, _model: {rule.name: candidates[:1] for rule, candidates in work if candidates},
    )

    findings = pattern_semantic.scan("a.md", "Feel free to ask me anything else.\n")

    assert [(item.rule, item.blocking) for item in findings] == [("ai_closer", True)]


def test_a_judge_that_confirms_nothing_produces_no_finding(monkeypatch) -> None:
    monkeypatch.setattr(pattern_semantic, "enabled", lambda: True)
    monkeypatch.setattr(pattern_semantic, "load_exemplars", lambda: EXEMPLARS)
    monkeypatch.setattr(
        pattern_semantic, "load_manifest",
        lambda: {"rules": {"ai_closer": {"action": "End when the answer is done.", "judge_precision": 1.0}}},
    )
    monkeypatch.setattr(pattern_semantic, "exemplar_vectors", lambda _exemplars: VECTORS)
    monkeypatch.setattr(pattern_semantic, "_vectors", lambda _texts: VECTORS)
    monkeypatch.setattr(pattern_semantic, "confirm_all", lambda _work, _model: {})

    assert pattern_semantic.scan("a.md", "Feel free to ask me anything else.\n") == ()
