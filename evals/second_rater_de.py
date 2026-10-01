#!/usr/bin/env python3
"""Compare a blind second rater with the first labels, because one labeler's taste would otherwise define both sides of every rule."""
import argparse
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

from ai_corpus_de import LABELS_PATH, REPOSITORY_ROOT, AiRow, load_ai_corpus, load_labels
from pattern_candidates_de import neighbour

SECOND_PATH = REPOSITORY_ROOT / "evals" / "pattern_labels_de_sonnet.jsonl"
DECIDED = ("violating", "clean")


def _rules() -> dict[str, object]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    return {rule.name: rule for rule in importlib.import_module("lib.german_rules").voted()}


def blind_items(labels: list[dict], texts: dict[int, str], rules: dict[str, object]) -> list[dict]:
    """No label and no reason, because a rater who sees the first verdict anchors on it."""
    items = []
    for row in labels:
        rule = rules[row["rule"]]
        item = {"rule": row["rule"], "line": row["line"], "muster": rule.german.title,
                "beschreibung": rule.german.description, "korrektur": rule.german.action, "text": texts[row["line"]]}
        if rule.boundary:
            item["abgrenzung"] = rule.boundary
        items.append(item)
    return items


def with_context(items: list[dict], corpus: list[AiRow]) -> list[dict]:
    """Neighbours for the first rater only, because it labeled with them and the second never had them."""
    by_line = {row.line: row for row in corpus}
    return [
        {**item, "davor": neighbour(corpus, by_line[item["line"]], -1), "danach": neighbour(corpus, by_line[item["line"]], 1)}
        for item in items
    ]


def relabeled(labels: list[dict], answers: list[dict]) -> list[dict]:
    """Whole rules only, because a half-replaced rule would mix two definitions in one kappa."""
    rules = {row["rule"] for row in answers}
    wanted = {(row["rule"], row["line"]) for row in labels if row["rule"] in rules}
    found = {(row["rule"], row["line"]): row for row in answers}
    if set(found) != wanted or len(found) != len(answers):
        raise ValueError(f"relabel covers {len(found)} rows, the rules {sorted(rules)} hold {len(wanted)}")
    return [found.get((row["rule"], row["line"]), row) for row in labels]


def merged_second(parts: list[list[dict]], labels: list[dict]) -> list[dict]:
    """Ordered like the first labels, because the comparison pairs rows by rule and line."""
    found = {(row["rule"], row["line"]): row for part in parts for row in part}
    missing = [(row["rule"], row["line"]) for row in labels if (row["rule"], row["line"]) not in found]
    if missing or len(found) != len(labels):
        raise ValueError(f"second rater covers {len(found)} of {len(labels)} rows, missing {missing[:5]}")
    return [found[(row["rule"], row["line"])] for row in labels]


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa over decided pairs, because raw agreement looks high when one class dominates."""
    if not pairs:
        return None
    observed = sum(first == second for first, second in pairs) / len(pairs)
    firsts = Counter(first for first, _ in pairs)
    seconds = Counter(second for _, second in pairs)
    expected = sum(firsts[label] * seconds[label] for label in DECIDED) / len(pairs) ** 2
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)


def agreement(first: list[dict], second: list[dict]) -> dict[str, object]:
    pairs = [(one["rule"], one["label"], other["label"]) for one, other in zip(first, second)]
    decided = [(rule, one, other) for rule, one, other in pairs if one in DECIDED and other in DECIDED]
    per_rule = {
        rule: {"kappa": kappa([(one, other) for name, one, other in decided if name == rule]),
               "pairs": sum(1 for name, _, _ in decided if name == rule),
               "agree": sum(1 for name, one, other in decided if name == rule and one == other)}
        for rule in dict.fromkeys(rule for rule, _, _ in pairs)
    }
    return {"kappa": kappa([(one, other) for _, one, other in decided]), "pairs": len(decided),
            "agree": sum(1 for _, one, other in decided if one == other), "rules": per_rule}


def disagreements(first: list[dict], second: list[dict]) -> list[dict]:
    return [
        {"rule": one["rule"], "line": one["line"], "first": one["label"], "second": other["label"],
         "second_reason": other.get("reason", "")}
        for one, other in zip(first, second) if one["label"] != other["label"]
    ]


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
    path.write_text("".join(encoder.encode(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


def _export(arguments: argparse.Namespace, labels: list[dict]) -> None:
    corpus = load_ai_corpus()
    chosen = [row for row in labels if arguments.rules is None or row["rule"] in arguments.rules]
    items = blind_items(chosen, {row.line: row.text for row in corpus}, _rules())
    _write(arguments.paths[0], with_context(items, corpus) if arguments.context else items)


def _relabel(arguments: argparse.Namespace, labels: list[dict]) -> None:
    _write(LABELS_PATH, relabeled(labels, _read(arguments.paths[0])))
    _write(SECOND_PATH, relabeled(_read(SECOND_PATH), _read(arguments.paths[1])))


def _merge(arguments: argparse.Namespace, labels: list[dict]) -> None:
    _write(SECOND_PATH, merged_second([_read(path) for path in arguments.paths], labels))


def _compare(_arguments: argparse.Namespace, labels: list[dict]) -> None:
    second = _read(SECOND_PATH)
    print(json.dumps({"agreement": agreement(labels, second), "disagreements": disagreements(labels, second)},
                     ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("export", "merge", "relabel", "compare"))
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--rules", nargs="*", default=None)
    parser.add_argument("--context", action="store_true")
    arguments = parser.parse_args()
    labels = load_labels(LABELS_PATH)
    steps = {"export": _export, "relabel": _relabel, "merge": _merge, "compare": _compare}
    steps[arguments.step](arguments, labels)


if __name__ == "__main__":
    main()
