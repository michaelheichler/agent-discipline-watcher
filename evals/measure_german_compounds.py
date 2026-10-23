#!/usr/bin/env python3
"""Score the shipped detector on words two raters labeled, because the de_long_compound gate cites these numbers."""
import gzip
import hashlib
import importlib
import json
import math
import random
import sys
from collections import Counter
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = REPOSITORY_ROOT / "evals" / "german_compound_labels.jsonl"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "german_compounds.json"
HELD_OUT = ("v3_main", "v3_addendum")
POPULATION_ADW_TYPES = 19897
POPULATION_HA_TYPES = 252
DRAWS = 20000
SEED = 20261026
NORMAL_QUANTILE_95 = 1.96
DECIDED = ("1", "0")
LABELS = ("1", "0", "?")

Labels = dict[str, str]


class Item(NamedTuple):
    word: str
    label: str


@cache
def detector() -> ModuleType:
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    return importlib.import_module("lib.german_compounds")


def read_rows() -> list[dict]:
    with LABELS_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def labels_of(rows: list[dict], samples: tuple[str, ...], rater: str = "rater1") -> Labels:
    return {row["word"]: row[rater] for row in rows if row["sample"] in samples}


def split_of(word: str) -> tuple[str, ...] | None:
    found = detector().compounds(word)
    return found[0].parts if found else None


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    quantile = NORMAL_QUANTILE_95
    proportion = successes / total
    denominator = 1 + quantile * quantile / total
    centre = (proportion + quantile * quantile / (2 * total)) / denominator
    spread = proportion * (1 - proportion) / total + quantile * quantile / (4 * total * total)
    half = quantile * math.sqrt(spread) / denominator
    return (round(centre - half, 4), round(centre + half, 4))


def score(items: list[Item]) -> dict:
    counts = Counter((split_of(item.word) is not None, item.label == "1") for item in items)
    true_positive, false_positive = counts[(True, True)], counts[(True, False)]
    false_negative, true_negative = counts[(False, True)], counts[(False, False)]
    predicted, actual = true_positive + false_positive, true_positive + false_negative
    return {
        "tp": true_positive, "fp": false_positive, "fn": false_negative, "tn": true_negative,
        "precision": round(true_positive / predicted, 4) if predicted else None,
        "precision_ci95": wilson(true_positive, predicted),
        "recall": round(true_positive / actual, 4) if actual else None,
        "recall_ci95": wilson(true_positive, actual),
    }


def gold_items(labels: Labels) -> list[Item]:
    return [Item(word, label) for word, label in labels.items() if label in DECIDED]


def agreed_items(first: Labels, second: Labels) -> list[Item]:
    return [Item(word, label) for word, label in first.items() if label in DECIDED and second.get(word) == label]


def kappa_three_way(first: Labels, second: Labels) -> float:
    words = [word for word in first if word in second]
    observed = sum(first[word] == second[word] for word in words) / len(words)
    count_first, count_second = Counter(first[word] for word in words), Counter(second[word] for word in words)
    expected = sum(count_first[label] / len(words) * count_second[label] / len(words) for label in LABELS)
    return round((observed - expected) / (1 - expected), 4)


def kappa_binary(first: Labels, second: Labels) -> dict:
    words = [word for word in first if first[word] in DECIDED and second.get(word) in DECIDED]
    observed = sum(first[word] == second[word] for word in words) / len(words)
    share_first = sum(first[word] == "1" for word in words) / len(words)
    share_second = sum(second[word] == "1" for word in words) / len(words)
    expected = share_first * share_second + (1 - share_first) * (1 - share_second)
    return {"items": len(words), "kappa": round((observed - expected) / (1 - expected), 4)}


def binary_counts(labels: Labels) -> dict:
    counter = Counter(label for label in labels.values() if label in DECIDED)
    return {"compounds": counter["1"], "non": counter["0"]}


def compound_shares(rows: list[dict]) -> dict:
    """Take shares from unenriched prose only, because the held-out samples were drawn to hold many compounds."""
    adw = binary_counts(labels_of(rows, ("share_adw",)))
    home_assistant = binary_counts(labels_of(rows, ("share_ha", "v2_ha")))
    weight_adw = POPULATION_ADW_TYPES / (POPULATION_ADW_TYPES + POPULATION_HA_TYPES)
    share_adw = adw["compounds"] / (adw["compounds"] + adw["non"])
    share_ha = home_assistant["compounds"] / (home_assistant["compounds"] + home_assistant["non"])
    return {
        "adw": adw, "ha": home_assistant, "weight_adw": round(weight_adw, 4),
        "pi_adw": round(share_adw, 4), "pi_ha": round(share_ha, 4),
        "pi_population_weighted": round(weight_adw * share_adw + (1 - weight_adw) * share_ha, 4),
    }


def projected_precision(recall: float, specificity: float, share: float) -> float:
    true_part = share * recall
    return true_part / (true_part + (1 - share) * (1 - specificity))


def projection_draw(rng: random.Random, counts: dict, shares: dict) -> float:
    recall = rng.betavariate(counts["tp"] + 1, counts["fn"] + 1)
    specificity = rng.betavariate(counts["tn"] + 1, counts["fp"] + 1)
    share_adw = rng.betavariate(shares["adw"]["compounds"] + 1, shares["adw"]["non"] + 1)
    share_ha = rng.betavariate(shares["ha"]["compounds"] + 1, shares["ha"]["non"] + 1)
    share = shares["weight_adw"] * share_adw + (1 - shares["weight_adw"]) * share_ha
    return projected_precision(recall, specificity, share)


def projection_interval(counts: dict, shares: dict) -> dict:
    rng = random.Random(SEED)
    draws = [projection_draw(rng, counts, shares) for _ in range(DRAWS)]
    draws.sort()
    return {
        "median": round(draws[len(draws) // 2], 4),
        "ci95": (round(draws[int(0.025 * DRAWS)], 4), round(draws[int(0.975 * DRAWS)], 4)),
    }


def gate_figures(agreed: list[Item], shares: dict) -> dict:
    counts = score(agreed)
    recall = counts["tp"] / (counts["tp"] + counts["fn"])
    specificity = counts["tn"] / (counts["tn"] + counts["fp"])
    point = projected_precision(recall, specificity, shares["pi_population_weighted"])
    return {
        "counts": counts,
        "specificity": round(specificity, 4),
        "specificity_ci95": wilson(counts["tn"], counts["tn"] + counts["fp"]),
        "projected_precision_point": round(point, 4),
        "projected_precision": projection_interval(counts, shares),
    }


def errors(agreed: list[Item]) -> dict:
    return {
        "false_positives": [(item.word, split_of(item.word)) for item in agreed if item.label == "0" and split_of(item.word)],
        "false_negatives": [item.word for item in agreed if item.label == "1" and split_of(item.word) is None],
    }


def lexicon_md5() -> str:
    with gzip.open(detector().LEXICON_PATH, "rb") as handle:
        return hashlib.md5(handle.read(), usedforsecurity=False).hexdigest()


def build_report() -> dict:
    rows = read_rows()
    first, second = labels_of(rows, HELD_OUT), labels_of(rows, HELD_OUT, "rater2")
    pools = {row["word"]: row["pool"] for row in rows if row["sample"] in HELD_OUT}
    agreed, shares = agreed_items(first, second), compound_shares(rows)
    main_agreed = agreed_items(labels_of(rows, ("v3_main",)), labels_of(rows, ("v3_main",), "rater2"))
    return {
        "lexicon_plain_md5": lexicon_md5(),
        "held_out": gate_figures(agreed, shares),
        "held_out_main_sample_only": gate_figures(main_agreed, shares),
        "precision_natural_general_pool": score([item for item in agreed if pools.get(item.word) == "general"]),
        "compound_shares": shares,
        "rater1_alone": score(gold_items(first)),
        "rater2_alone": score(gold_items(second)),
        "kappa_three_way": kappa_three_way(first, second),
        "kappa_binary": kappa_binary(first, second),
        "label_counts": {"rater1": dict(Counter(first.values())), "rater2": dict(Counter(second.values()))},
        **errors(agreed),
    }


def main() -> None:
    report = build_report()
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    held_out = report["held_out"]
    print("recall", held_out["counts"]["recall"], "specificity", held_out["specificity"],
          "projected precision", held_out["projected_precision_point"])


if __name__ == "__main__":
    main()
