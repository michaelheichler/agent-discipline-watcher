"""Guard the tie rule, because a tie broken by hand or a dropped row would bias the German precision either way."""
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


judge = _evals_module("adjudicate_de")


def _row(line: int, label: str, rule: str = "de_passive_voice") -> dict:
    return {"rule": rule, "line": line, "label": label}


@pytest.mark.parametrize(
    ("votes", "expected"),
    (
        (["violating", "clean", "violating"], "violating"),
        (["violating", "clean", "clean"], "clean"),
        (["clean", "undecided", "clean"], "clean"),
        (["violating", "clean", "undecided"], "undecided"),
    ),
)
def test_two_decided_votes_settle_a_row(votes: list[str], expected: str) -> None:
    assert judge.majority(votes) == expected


def test_agreed_rows_pass_through_and_disputed_rows_take_the_majority() -> None:
    first = [_row(1, "clean"), _row(2, "violating")]
    second = [_row(1, "clean"), _row(2, "clean")]

    rows = judge.adjudicated(first, second, [_row(2, "violating")])

    assert [(row["line"], row["label"], row["basis"]) for row in rows] == [(1, "clean", "agreed"), (2, "violating", "majority")]


def test_only_disputed_rows_go_to_the_third_rater() -> None:
    first = [_row(1, "clean"), _row(2, "violating")]
    second = [_row(1, "clean"), _row(2, "clean")]

    assert [row["line"] for row in judge.disputed(first, second)] == [2]


def test_a_disputed_row_the_third_rater_skipped_is_refused() -> None:
    with pytest.raises(ValueError):
        judge.adjudicated([_row(2, "violating")], [_row(2, "clean")], [])
