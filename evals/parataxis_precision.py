#!/usr/bin/env python3
"""Hand raters blind parataxis hits and score their labels, because a hit rate alone says nothing about whether an editor would join the run."""
import argparse
import json
from pathlib import Path
from typing import NamedTuple

from german_static_precision import BAR, recommend, wilson
from german_static_sample import opaque, read_jsonl
from measure_parataxis import EVALS, OUTPUT_PATH as HIT_RATE_PATH, SAMPLE_PATH
from second_rater_de import kappa

ITEMS_PATH = EVALS / "parataxis_items.jsonl"
OUTPUT_PATH = EVALS / "parataxis_precision.json"
RATERS = ("sonnet", "luna")
THIRD = "opus"
VIOLATING = "violating"
DECIDED = (VIOLATING, "clean")
QUESTION = (
    "Would a careful editor of reader-facing prose join at least two of the flagged sentences into one, "
    "with a subordinate clause, a relative clause, an apposition, a participle or infinitive group, "
    "or and or but, because the split reads as choppy telegram style? Answer violating if yes. "
    "Answer clean if the split reads well as it stands, or the text is not running prose."
)


class Inputs(NamedTuple):
    sample: list[dict]
    decided: dict[str, str]
    hit_rates: dict


def labels_path(rater: str) -> Path:
    return EVALS / f"parataxis_labels_{rater}.jsonl"


def blind_items(sample: list[dict]) -> list[dict]:
    """Text and question only, because a rater who sees the corpus side anchors on who wrote it."""
    return [{"id": opaque(row["id"]), "question": QUESTION, "flagged": row["run"], "paragraph": row["paragraph"]}
            for row in sample]


def _labels(rater: str, sample: list[dict]) -> dict[str, str]:
    """Refuse a partial label set, because a silent gap would raise precision on the rows left."""
    answers = {row["id"]: row["label"] for row in read_jsonl(labels_path(rater))}
    wanted = {opaque(row["id"]) for row in sample}
    if set(answers) != wanted or set(answers.values()) - set(DECIDED):
        raise ValueError(f"{rater}: {len(wanted & set(answers))} of {len(wanted)} rows answered")
    return answers


def decided_labels(sample: list[dict]) -> dict[str, str]:
    """Majority of three, because the third rater only sees rows where the first two split."""
    first, second = (_labels(rater, sample) for rater in RATERS)
    third = {row["id"]: row["label"] for row in read_jsonl(labels_path(THIRD))}
    split = {key for key in first if first[key] != second[key]}
    if set(third) != split:
        raise ValueError(f"{THIRD}: answered {len(set(third) & split)} of {len(split)} split rows")
    return {key: third.get(key, first[key]) for key in first}


def rule_record(rule: str, inputs: Inputs) -> dict[str, object]:
    rows = [row for row in inputs.sample if row["rule"] == rule]
    keys = [opaque(row["id"]) for row in rows]
    violating = sum(inputs.decided[key] == VIOLATING for key in keys)
    lower, upper = wilson(violating, len(rows))
    first, second = (_labels(rater, inputs.sample) for rater in RATERS)
    human_rate = inputs.hit_rates["rules"][rule]["rates"]["human"]["per_1000"]
    verdict, reason = recommend(lower, violating / len(rows), human_rate)
    genres = sorted({f"{row['side']}/{row['genre']}" for row in rows})
    by_genre = {
        genre: [inputs.decided[opaque(row["id"])] == VIOLATING for row in rows if f"{row['side']}/{row['genre']}" == genre]
        for genre in genres
    }
    return {
        "n": len(rows), "violating": violating, "precision": round(violating / len(rows), 4),
        "wilson_95": [lower, upper], "kappa": kappa([(first[key], second[key]) for key in keys]),
        "by_genre": {genre: {"n": len(found), "violating": sum(found)} for genre, found in by_genre.items()},
        "human_per_1000_paragraphs": human_rate, "bar": BAR, "recommendation": verdict, "reason": reason,
    }


def score() -> dict[str, object]:
    sample = read_jsonl(SAMPLE_PATH)
    inputs = Inputs(sample, decided_labels(sample), json.loads(HIT_RATE_PATH.read_text(encoding="utf-8")))
    rules = sorted({row["rule"] for row in sample})
    return {"raters": [*RATERS, THIRD], "question": QUESTION, "rules": {rule: rule_record(rule, inputs) for rule in rules}}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    encoder = json.JSONEncoder(ensure_ascii=False)
    path.write_text("".join(encoder.encode(row) + "\n" for row in rows), encoding="utf-8")


def _disputes() -> list[dict]:
    sample = read_jsonl(SAMPLE_PATH)
    first, second = (_labels(rater, sample) for rater in RATERS)
    return [item for item in blind_items(sample) if first[item["id"]] != second[item["id"]]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("export", "disputes", "score"))
    arguments = parser.parse_args()
    if arguments.step == "export":
        _write_jsonl(ITEMS_PATH, blind_items(read_jsonl(SAMPLE_PATH)))
        print(ITEMS_PATH)
        return
    if arguments.step == "disputes":
        _write_jsonl(EVALS / "parataxis_disputes.jsonl", _disputes())
        print(EVALS / "parataxis_disputes.jsonl")
        return
    report = score()
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
