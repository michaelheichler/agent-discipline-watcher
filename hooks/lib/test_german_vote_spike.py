"""The German vote spike must score the shipped vote, because a figure from a different vote would mislead T-010."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

EVALS = Path(__file__).resolve().parents[2] / "evals"


def _evals_module(name: str) -> ModuleType:
    """Imported by name, because the eval scripts import their siblings by name and not as a package."""
    if str(EVALS) not in sys.path:
        sys.path.insert(0, str(EVALS))
    return importlib.import_module(name)


spike = _evals_module("qualify_embeddings_de")
EAST = (1.0, 0.0)
NORTH = (0.0, 1.0)
NEAR_EAST = (0.9, 0.1)


def test_the_vote_follows_the_majority_of_the_nearest_neighbours() -> None:
    neighbours = [("violating", EAST), ("violating", NEAR_EAST), ("clean", NORTH), ("clean", NORTH)]

    assert spike.votes_violating((0.95, 0.05), neighbours, 1)
    assert not spike.votes_violating((0.05, 0.95), neighbours, 3)


def test_leave_one_out_reports_each_class_on_its_own() -> None:
    neighbours = [("violating", EAST), ("violating", NEAR_EAST), ("clean", NORTH), ("clean", (0.1, 0.9))]

    scored = spike.leave_one_out(neighbours, 1)

    assert scored["violating_flagged"]["flagged"] == 2
    assert scored["clean_flagged"]["flagged"] == 0
    assert scored["clean_flagged"]["total"] == 2


def test_a_vote_that_flags_everything_shows_as_a_flagged_clean_class() -> None:
    neighbours = [("violating", EAST), ("violating", NEAR_EAST), ("violating", (0.8, 0.2)), ("clean", NORTH)]

    scored = spike.leave_one_out(neighbours, 3)

    assert scored["clean_flagged"]["rate"] == 1.0


def test_queries_skip_shipped_and_undecided_rows() -> None:
    labels = [
        {"line": 1, "label": "violating"}, {"line": 2, "label": "violating"},
        {"line": 3, "label": "clean"}, {"line": 4, "label": "undecided"},
    ]
    texts = {1: "eins", 2: "zwei", 3: "drei", 4: "vier"}

    queries = spike.rule_queries(labels, texts, shipped_rows={1})

    assert queries == [spike.Query(spike.HELD_OUT, "zwei"), spike.Query(spike.NEAR_MISS, "drei")]


def test_the_labeled_pool_adds_held_out_rows_as_neighbours_and_leaves_humans_out() -> None:
    queries = [
        (spike.Query(spike.HELD_OUT, "a"), EAST), (spike.Query(spike.NEAR_MISS, "b"), NORTH),
        (spike.Query(spike.HUMAN, "c"), NEAR_EAST),
    ]

    pool = spike.labeled_pool([("clean", NORTH)], queries)

    assert [label for label, _ in pool] == ["clean", "violating", "clean"]
