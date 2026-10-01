"""The German precision gate reads a lower bound over blind labels, because a lucky 20 of 20 must not unlock a hard block."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

EVALS = Path(__file__).resolve().parents[2] / "evals"


def _evals_module(name: str) -> ModuleType:
    """Imported by name, because the eval scripts import their siblings by name and not as a package."""
    if str(EVALS) not in sys.path:
        sys.path.insert(0, str(EVALS))
    return importlib.import_module(name)


sample = _evals_module("german_static_sample")
precision = _evals_module("german_static_precision")


def _hit(rule: str, corpus: str, line: int) -> dict:
    return {"rule": rule, "corpus": corpus, "line": line, "side": "human", "genre": "encyclopedia", "finding_line": 1}


def test_twenty_of_twenty_stays_under_the_bar() -> None:
    lower, upper = precision.wilson(20, 20)

    assert lower == pytest.approx(0.8389, abs=1e-4)
    assert upper == 1.0
    assert precision.recommend(lower, 1.0, 0.0)[0] == "observe"


def test_a_rule_clearing_the_bar_on_its_lower_bound_enforces() -> None:
    assert precision.recommend(0.86, 0.97, 50.0)[0] == "enforce"


def test_a_noisy_rule_on_human_text_turns_off() -> None:
    assert precision.recommend(0.10, 0.25, 40.0)[0] == "off"


def test_a_noisy_rule_that_human_text_rarely_trips_keeps_observing() -> None:
    assert precision.recommend(0.10, 0.25, 0.5)[0] == "observe"


def test_finding_line_maps_to_its_paragraph_across_wrapped_lines() -> None:
    paragraphs = ["erste Zeile\nzweite Zeile", "dritter Absatz", "vierter"]

    assert sample.paragraph_at(paragraphs, 2) == paragraphs[0]
    assert sample.paragraph_at(paragraphs, 4) == paragraphs[1]
    assert sample.paragraph_at(paragraphs, 6) == paragraphs[2]
    with pytest.raises(ValueError):
        sample.paragraph_at(paragraphs, 3)


def test_document_rules_sample_the_paragraph_corpus() -> None:
    hits = [_hit("de_sentence_length", "human_sentences", 1), _hit("de_sentence_length", "paragraphs", 2)]

    assert sample.designated("de_sentence_length", hits) == [hits[1]]


def test_draw_caps_each_rule_and_repeats_under_the_seed() -> None:
    hits = [_hit("de_filler_word", "human_sentences", line) for line in range(1, 60)]

    first, second = sample.draw(hits), sample.draw(hits)

    assert len(first) == sample.PER_RULE
    assert first == second


def test_a_rater_sees_no_corpus_name_in_the_item_id() -> None:
    assert "human" not in sample.opaque("de_filler_word:human_sentences:7")


def test_a_partial_answer_set_is_refused(tmp_path: Path) -> None:
    refs = [{"id": "de_triad:ai_sentences:1"}, {"id": "de_triad:ai_sentences:2"}]
    answers = tmp_path / "answers.jsonl"
    answers.write_text(json.dumps({"id": sample.opaque(refs[0]["id"]), "label": "clean"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        sample.answers_for(refs, [answers], "sonnet")
