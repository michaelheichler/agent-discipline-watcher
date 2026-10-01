#!/usr/bin/env python3
"""Settle each rater disagreement by a third blind vote, because precision needs one label per row and neither rater outranks the other."""
import argparse
from collections import Counter
from pathlib import Path

from ai_corpus_de import ADJUDICATED_PATH, LABELS_PATH, load_ai_corpus, load_labels
from second_rater_de import DECIDED, SECOND_PATH, _read, _rules, _write, blind_items, with_context

UNDECIDED = "undecided"


def disputed(first: list[dict], second: list[dict]) -> list[dict]:
    return [one for one, other in zip(first, second) if one["label"] != other["label"]]


def majority(votes: list[str]) -> str:
    """Two of three decided votes, because one rater plus an undecided third is no majority."""
    winners = [label for label, count in Counter(vote for vote in votes if vote in DECIDED).items() if count >= 2]
    return winners[0] if winners else UNDECIDED


def adjudicated(first: list[dict], second: list[dict], third: list[dict]) -> list[dict]:
    """Every row kept in first-label order, because the exemplar draw reads a prefix of the seeded order."""
    answers = {(row["rule"], row["line"]): row["label"] for row in third}
    missing = [(row["rule"], row["line"]) for row in disputed(first, second) if (row["rule"], row["line"]) not in answers]
    if missing:
        raise ValueError(f"the adjudicator left {len(missing)} disputed rows open, first {missing[:3]}")
    rows = []
    for one, other in zip(first, second):
        key = (one["rule"], one["line"])
        if one["label"] == other["label"]:
            rows.append({"rule": one["rule"], "line": one["line"], "label": one["label"], "basis": "agreed"})
            continue
        votes = [one["label"], other["label"], answers[key]]
        rows.append({"rule": one["rule"], "line": one["line"], "label": majority(votes), "basis": "majority", "votes": votes})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("export", "merge"))
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    first, second = load_labels(LABELS_PATH), _read(SECOND_PATH)
    if arguments.step == "export":
        corpus = load_ai_corpus()
        items = blind_items(disputed(first, second), {row.line: row.text for row in corpus}, _rules())
        _write(arguments.path, with_context(items, corpus))
        return
    _write(ADJUDICATED_PATH, adjudicated(first, second, _read(arguments.path)))


if __name__ == "__main__":
    main()
