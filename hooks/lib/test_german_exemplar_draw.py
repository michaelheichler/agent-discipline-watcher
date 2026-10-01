"""The German violating draw must be repeatable, because a hand-picked exemplar carries the picker's taste into the vote."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

EVALS = Path(__file__).resolve().parents[2] / "evals"
RULE = "de_vague_authority"


def _evals_module(name: str) -> ModuleType:
    """Imported by name, because the eval scripts import their siblings by name and not as a package."""
    if str(EVALS) not in sys.path:
        sys.path.insert(0, str(EVALS))
    return importlib.import_module(name)


ai_corpus_de = _evals_module("ai_corpus_de")
builder = _evals_module("build_pattern_exemplars_de")
drawing = _evals_module("pattern_candidates_de")


def _row(line: int, text: str):
    return ai_corpus_de.AiRow(line, "coling", "gpt-3.5-turbo", 100 + line, text)


def _label(line: int, label: str, rule: str = RULE) -> dict:
    return {"rule": rule, "line": line, "label": label, "reason": "test"}


CORPUS = [_row(line, f"Experten warnen seit Wochen vor der Lage in Region {line}.") for line in range(1, 9)]


def test_the_first_four_violating_labels_become_exemplars_in_label_order() -> None:
    labels = [_label(5, "violating"), _label(2, "clean"), _label(7, "violating"), _label(1, "violating"),
              _label(3, "violating"), _label(8, "violating")]

    chosen, short = builder.violating_side(labels, CORPUS, (RULE,))

    assert [row["row"] for row in chosen] == [5, 7, 1, 3]
    assert {row["label"] for row in chosen} == {"violating"}
    assert chosen[0]["origin"] == "assistant/coling"
    assert chosen[0]["document"] == 105
    assert short == {}


def test_a_rule_with_three_violating_labels_stays_silent() -> None:
    labels = [_label(1, "violating"), _label(2, "violating"), _label(3, "undecided"), _label(4, "violating")]

    chosen, short = builder.violating_side(labels, CORPUS, (RULE, "de_false_agency"))

    assert not chosen
    assert short == {RULE: 3, "de_false_agency": 0}


def test_the_clean_side_takes_two_labeled_near_misses_and_two_human_rows() -> None:
    labels = [_label(line, "clean") for line in (2, 4, 6)] + [_label(1, "violating")]

    assistant = builder.assistant_clean_side(labels, CORPUS, (RULE,))

    assert len(assistant) == 2
    assert {row["row"] for row in assistant} <= {2, 4, 6}
    assert {row["label"] for row in assistant} == {"clean"}
    assert builder.human_per_genre(assistant, (RULE,)) == {RULE: 1}


def test_a_rule_without_two_near_misses_takes_four_human_rows() -> None:
    assistant = builder.assistant_clean_side([_label(2, "clean")], CORPUS, (RULE,))

    assert not assistant
    assert builder.human_per_genre(assistant, (RULE,)) == {RULE: 2}


def test_the_near_miss_draw_repeats_under_the_same_seed() -> None:
    labels = [_label(line, "clean") for line in range(1, 9)]

    first = builder.assistant_clean_side(labels, CORPUS, (RULE,), seed=11)

    assert first == builder.assistant_clean_side(labels, CORPUS, (RULE,), seed=11)


def test_labels_that_follow_the_seeded_order_pass_the_prefix_check() -> None:
    order = [row.line for row in drawing.candidates(RULE, CORPUS)]
    labels = [_label(line, "clean") for line in order[:3]]

    assert not drawing.off_prefix_rules(labels, CORPUS)


def test_labels_that_skip_a_seeded_candidate_fail_the_prefix_check() -> None:
    order = [row.line for row in drawing.candidates(RULE, CORPUS)]
    labels = [_label(order[0], "clean"), _label(order[2], "violating")]

    assert drawing.off_prefix_rules(labels, CORPUS) == [RULE]


def test_the_candidate_order_repeats_under_the_same_seed_and_moves_under_another() -> None:
    first = [row.line for row in drawing.candidates(RULE, CORPUS, seed=7)]

    assert first == [row.line for row in drawing.candidates(RULE, CORPUS, seed=7)]
    assert sorted(first) == list(range(1, 9))
    assert any([row.line for row in drawing.candidates(RULE, CORPUS, seed=seed)] != first for seed in (8, 9, 10))
