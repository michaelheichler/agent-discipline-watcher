#!/usr/bin/env python3
"""Score adjudicated German rule labels against the 0.85 bar, because decision Q23 lets only a measured rule block."""
import json
import math
from collections import defaultdict
from typing import NamedTuple

from german_static_sample import (
    ADJUDICATED, FIRST, SAMPLE_PATH, SECOND, THIRD, labels_path, read_jsonl,
)
from measure_german_hit_rate import EVALS, OUTPUT_PATH as HIT_RATE_PATH
from second_rater_de import kappa

OUTPUT_PATH = EVALS / "german_static_precision.json"
BAR = 0.85
WILSON_Z = 1.96
LOW_PRECISION = 0.5
FREQUENT_HUMAN_PER_1000 = 5.0
RATER_MODELS = {FIRST: "sonnet", SECOND: "gpt-6-luna", THIRD: "opus"}
VIOLATING = "violating"


def wilson(hits: int, total: int) -> tuple[float, float]:
    """Gate on the low end, because 20 rows at 1.0 still leave the true rate as low as 0.84."""
    share = hits / total
    denominator = 1 + WILSON_Z**2 / total
    centre = (share + WILSON_Z**2 / (2 * total)) / denominator
    spread = WILSON_Z * math.sqrt(share * (1 - share) / total + WILSON_Z**2 / (4 * total**2)) / denominator
    return round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4)


def _corpus_kind(corpus: str) -> str:
    return "paragraphs" if corpus == "paragraphs" else "sentences"


def _rates(hit_rates: dict, rule: str, corpus: str) -> dict[str, float | None]:
    record = hit_rates["rules"][rule][_corpus_kind(corpus)]
    return {"human": record["human"]["per_1000"], "ai": record["ai"]["per_1000"]}


def recommend(lower: float, precision: float, human_rate: float | None) -> tuple[str, str]:
    if lower >= BAR:
        return "enforce", f"lower bound {lower:.2f} clears the {BAR} bar"
    if precision < LOW_PRECISION and (human_rate or 0.0) >= FREQUENT_HUMAN_PER_1000:
        return "off", f"precision {precision:.2f} at {human_rate} human hits per 1000"
    return "observe", f"lower bound {lower:.2f} sits under the {BAR} bar"


class Inputs(NamedTuple):
    raters: dict[str, dict]
    hit_rates: dict


def rule_record(rule: str, rows: list[dict], inputs: Inputs) -> dict[str, object]:
    raters, hit_rates = inputs
    total = len(rows)
    violating = sum(row["label"] == VIOLATING for row in rows)
    precision = round(violating / total, 4)
    lower, upper = wilson(violating, total)
    rates = _rates(hit_rates, rule, rows[0]["corpus"])
    pairs = [(raters[FIRST][row["id"]], raters[SECOND][row["id"]]) for row in rows]
    verdict, reason = recommend(lower, precision, rates["human"])
    return {
        "n": total, "violating": violating, "precision": precision, "wilson_95": [lower, upper],
        "kappa": kappa(pairs), "rater_agreement": sum(one == other for one, other in pairs),
        "sampled_from": _corpus_kind(rows[0]["corpus"]), "sampled_human": sum(row["side"] == "human" for row in rows),
        "per_1000": rates, "gate": hit_rates["rules"][rule]["gate"], "recommendation": verdict, "reason": reason,
    }


def build_report() -> dict[str, object]:
    adjudicated = read_jsonl(labels_path(ADJUDICATED))
    raters = {name: {row["id"]: row["label"] for row in read_jsonl(labels_path(name))} for name in (FIRST, SECOND)}
    hit_rates = json.loads(HIT_RATE_PATH.read_text(encoding="utf-8"))
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for row in adjudicated:
        by_rule[row["rule"]].append(row)
    all_pairs = [(raters[FIRST][row["id"]], raters[SECOND][row["id"]]) for row in adjudicated]
    sampled = {row["id"] for row in read_jsonl(SAMPLE_PATH)}
    if sampled != {row["id"] for row in adjudicated}:
        raise ValueError("adjudicated labels do not cover the sample")
    return {
        "bar": BAR, "gate_reads": "wilson_95 lower bound", "raters": RATER_MODELS,
        "off_when": {"precision_below": LOW_PRECISION, "human_per_1000_at_least": FREQUENT_HUMAN_PER_1000},
        "labels": len(adjudicated), "kappa": kappa(all_pairs),
        "rater_agreement": sum(one == other for one, other in all_pairs),
        "third_rater_rows": sum(row[THIRD] is not None for row in adjudicated),
        "rules": {rule: rule_record(rule, rows, Inputs(raters, hit_rates)) for rule, rows in sorted(by_rule.items())},
        "silent_rules": sorted(rule for rule in hit_rates["rules"] if rule not in by_rule),
    }


def main() -> None:
    report = build_report()
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    for rule, record in report["rules"].items():
        print(f"{rule:<28} n={record['n']:>2} p={record['precision']:.2f} lo={record['wilson_95'][0]:.2f} "
              f"human={record['per_1000']['human']} {record['recommendation']}")
    print(f"kappa {report['kappa']} over {report['labels']} labels")


if __name__ == "__main__":
    main()
