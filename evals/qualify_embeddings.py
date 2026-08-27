#!/usr/bin/env python3
"""Votes among a pattern's own two classes, because nearest-exemplar cosine measured topic and caught 1 sentence in 273."""
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.embedding_client import embed, embeddings_urls

BENCHMARK_PATH = REPOSITORY_ROOT / "evals" / "benchmark_patterns.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "benchmark_manifest.json"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "qualification.json"
BATCH_SIZE = 64
# WHY: Swept rather than fixed, so a no-go condemns the method and not one hyperparameter.
NEIGHBOUR_COUNTS = (1, 3, 5, 9, 15, 25)
# WHY: A candidate stage is judged on what it misses, since the judge behind it removes what it over-flags.
RECALL_FLOOR = 0.85
WILSON_Z = 1.96
VIOLATING = "violating"


class Scored(NamedTuple):
    rule: str
    neighbours: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    @property
    def precision(self) -> float | None:
        predicted = self.true_positive + self.false_positive
        return self.true_positive / predicted if predicted else None

    @property
    def recall(self) -> float | None:
        actual = self.true_positive + self.false_negative
        return self.true_positive / actual if actual else None


def _wilson(hits: int, total: int) -> tuple[float, float] | None:
    """Reported as an interval because a ratio over 150 rows reads as exact and is not."""
    if not total:
        return None
    share = hits / total
    denominator = 1 + WILSON_Z**2 / total
    centre = (share + WILSON_Z**2 / (2 * total)) / denominator
    spread = WILSON_Z * math.sqrt(share * (1 - share) / total + WILSON_Z**2 / (4 * total**2)) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def load_rows() -> list[dict]:
    with BENCHMARK_PATH.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def embed_all(texts: tuple[str, ...]) -> dict[str, tuple[float, ...]]:
    vectors: dict[str, tuple[float, ...]] = {}
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        answered = embed(batch)
        if answered is None:
            raise ValueError(f"no embedding server answered {embeddings_urls()!r}")
        vectors.update(zip(batch, answered))
        print(f"  embedded {min(start + BATCH_SIZE, len(texts))} of {len(texts)}", flush=True)
    return vectors


def _similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(one * other for one, other in zip(left, right))


def _neighbour_labels(
    vector: tuple[float, ...], development: list[tuple[str, tuple[float, ...]]]
) -> list[str]:
    return [name for name, _ in sorted(development, key=lambda entry: -_similarity(vector, entry[1]))]


def _ranked(rows: list[dict], vectors: dict[str, tuple[float, ...]]) -> list[tuple[str, list[str]]]:
    development = [(row["label"], vectors[row["text"]]) for row in rows if row["split"] == "development"]
    held_out = [(row["label"], vectors[row["text"]]) for row in rows if row["split"] == "held_out"]
    return [(label, _neighbour_labels(vector, development)) for label, vector in held_out]


def score_rule(rule: str, ranked: list[tuple[str, list[str]]], neighbours: int) -> Scored:
    tallies: Counter = Counter()
    for label, names in ranked:
        votes = Counter(names[:neighbours])
        predicted = votes.most_common(1)[0][0] == VIOLATING
        tallies[(label == VIOLATING, predicted)] += 1
    return Scored(
        rule, neighbours,
        tallies[(True, True)], tallies[(False, True)], tallies[(True, False)], tallies[(False, False)],
    )


def _record(scored: Scored) -> dict[str, object]:
    flagged = scored.true_positive + scored.false_positive
    actual = scored.true_positive + scored.false_negative
    recall_interval = _wilson(scored.true_positive, actual)
    return {
        "neighbours": scored.neighbours,
        "precision": scored.precision,
        "precision_interval": _wilson(scored.true_positive, flagged),
        "recall": scored.recall,
        "recall_interval": recall_interval,
        "flagged": flagged,
        "held_out_violating": actual,
        "held_out_clean": scored.false_positive + scored.true_negative,
        "judge_calls_per_true_finding": round(flagged / scored.true_positive, 2) if scored.true_positive else None,
        "clears_floor": bool(recall_interval and recall_interval[0] >= RECALL_FLOOR),
    }


def _best(rule: str, ranked: list[tuple[str, list[str]]]) -> dict[str, object]:
    """Ranks on recall because this stage only proposes candidates, and the judge behind it decides what is real."""
    records = [_record(score_rule(rule, ranked, count)) for count in NEIGHBOUR_COUNTS]
    return max(records, key=lambda row: ((row["recall"] or 0.0), -row["flagged"]))


def build_report(rules: dict[str, dict], endpoint: str) -> dict[str, object]:
    passing = sorted(rule for rule, row in rules.items() if row["clears_floor"])
    return {
        "benchmark_sha256": json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["sha256"],
        "endpoint": endpoint,
        "neighbour_counts": list(NEIGHBOUR_COUNTS),
        "recall_floor": RECALL_FLOOR,
        "rules": rules,
        "rules_clearing_the_floor": passing,
        "verdict": "go" if passing else "no-go",
    }


def _format(rule: str, row: dict) -> str:
    interval = row["recall_interval"]
    span = f"[{interval[0]:.2f}, {interval[1]:.2f}]" if interval else "[none]"
    recall = f"{row['recall']:.4f}" if row["recall"] is not None else "  none"
    precision = f"{row['precision']:.4f}" if row["precision"] is not None else "  none"
    return (
        f"{rule:<24} k={row['neighbours']:<3} {recall} {span:<14} {precision} "
        f"  {row['flagged']:>4}/{row['held_out_violating']:>4}"
    )


def main() -> None:
    rows = load_rows()
    texts = tuple(sorted({row["text"] for row in rows}))
    print(f"{len(rows)} rows over {len({row['rule'] for row in rows})} rules, {len(texts)} unique texts")
    vectors = embed_all(texts)
    rules = {
        rule: _best(rule, _ranked([row for row in rows if row["rule"] == rule], vectors))
        for rule in sorted({row["rule"] for row in rows})
    }
    report = build_report(rules, embeddings_urls()[0] if embeddings_urls() else "")
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{'rule':<24} {'best':<5} {'recall':<9} {'95 percent':<14} {'precision':<9} {'flagged/pos':>10}")
    for rule in sorted(rules, key=lambda name: -(rules[name]["recall_interval"] or (0.0,))[0]):
        print(_format(rule, rules[rule]))
    print(f"{len(report['rules_clearing_the_floor'])} of {len(rules)} rules clear a {RECALL_FLOOR} recall floor")


if __name__ == "__main__":
    main()
