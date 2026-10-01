#!/usr/bin/env python3
"""Compare a blind second rater with the first labels, because one labeler's taste would otherwise define both sides of every rule."""
import argparse
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

from ai_corpus_de import LABELS_PATH, REPOSITORY_ROOT, load_ai_corpus, load_labels

SECOND_PATH = REPOSITORY_ROOT / "evals" / "pattern_labels_de_sonnet.jsonl"
DECIDED = ("violating", "clean")


def _rules() -> dict[str, object]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    return {rule.name: rule for rule in importlib.import_module("lib.german_rules").voted()}


def blind_items(labels: list[dict], texts: dict[int, str], rules: dict[str, object]) -> list[dict]:
    """No label and no reason, because a rater who sees the first verdict anchors on it."""
    return [
        {"rule": row["rule"], "line": row["line"], "muster": rules[row["rule"]].german.title,
         "beschreibung": rules[row["rule"]].german.description, "korrektur": rules[row["rule"]].german.action,
         "text": texts[row["line"]]}
        for row in labels
    ]


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("export", "merge", "compare"))
    parser.add_argument("paths", nargs="*", type=Path)
    arguments = parser.parse_args()
    labels = load_labels(LABELS_PATH)
    if arguments.step == "export":
        texts = {row.line: row.text for row in load_ai_corpus()}
        _write(arguments.paths[0], blind_items(labels, texts, _rules()))
    elif arguments.step == "merge":
        _write(SECOND_PATH, merged_second([_read(path) for path in arguments.paths], labels))
    else:
        second = _read(SECOND_PATH)
        print(json.dumps({"agreement": agreement(labels, second), "disagreements": disagreements(labels, second)},
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
