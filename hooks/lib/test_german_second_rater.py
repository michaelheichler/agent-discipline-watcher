"""The rater comparison must count chance agreement, because two raters who both say clean to everything agree without judging."""
from __future__ import annotations

import importlib
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


rater = _evals_module("second_rater_de")


def _row(line: int, label: str, rule: str = "de_passive_voice") -> dict:
    return {"rule": rule, "line": line, "label": label}


def test_full_agreement_on_both_classes_scores_one() -> None:
    assert rater.kappa([("violating", "violating"), ("clean", "clean")]) == 1.0


def test_agreement_no_better_than_chance_scores_zero() -> None:
    pairs = [("violating", "violating"), ("violating", "clean"), ("clean", "violating"), ("clean", "clean")]

    assert rater.kappa(pairs) == 0.0


def test_a_textbook_table_gives_its_known_kappa() -> None:
    pairs = [("violating", "violating")] * 20 + [("violating", "clean")] * 5 + [("clean", "violating")] * 10 + [("clean", "clean")] * 15

    assert rater.kappa(pairs) == 0.4


def test_undecided_rows_stay_out_of_kappa_but_show_as_disagreements() -> None:
    first = [_row(1, "violating"), _row(2, "clean"), _row(3, "undecided")]
    second = [_row(1, "violating"), _row(2, "clean"), _row(3, "clean")]

    assert rater.agreement(first, second)["pairs"] == 2
    assert [row["line"] for row in rater.disagreements(first, second)] == [3]


def test_a_second_rater_missing_a_row_is_refused() -> None:
    labels = [_row(1, "clean"), _row(2, "clean")]

    with pytest.raises(ValueError):
        rater.merged_second([[_row(1, "clean")]], labels)


def test_parts_merge_back_into_first_label_order() -> None:
    labels = [_row(5, "clean"), _row(3, "clean")]

    merged = rater.merged_second([[_row(3, "violating")], [_row(5, "clean")]], labels)

    assert [row["line"] for row in merged] == [5, 3]


def test_a_relabel_replaces_only_the_rules_it_covers() -> None:
    labels = [_row(1, "clean", "de_a"), _row(2, "clean", "de_b"), _row(3, "clean", "de_a")]

    merged = rater.relabeled(labels, [_row(3, "violating", "de_a"), _row(1, "violating", "de_a")])

    assert [(row["line"], row["label"]) for row in merged] == [(1, "violating"), (2, "clean"), (3, "violating")]


def test_a_relabel_that_skips_a_row_of_its_rule_is_refused() -> None:
    labels = [_row(1, "clean", "de_a"), _row(3, "clean", "de_a")]

    with pytest.raises(ValueError):
        rater.relabeled(labels, [_row(1, "violating", "de_a")])
