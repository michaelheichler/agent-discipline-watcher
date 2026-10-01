#!/usr/bin/env python3
"""Order German AI sentences by seed for labeling, because the violating side must come from a draw anyone can repeat."""
import argparse
import functools
import importlib
import random
import re
import sys
from collections.abc import Mapping

from ai_corpus_de import REPOSITORY_ROOT, AiRow, ai_corpus_digest, load_ai_corpus, load_labels
from build_pattern_exemplars_de import SEED, usable_text

MIN_WORDS = 4
BATCH = 16


@functools.cache
def candidate_patterns() -> Mapping[str, re.Pattern[str]]:
    """Read from the rule modules, because the hook must draw the same candidates the labels cover."""
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    return importlib.import_module("lib.german_rules").triggers()


def candidates(rule: str, corpus: list[AiRow], seed: int = SEED) -> list[AiRow]:
    """Seeded per rule, because the labels cover a prefix of this order and any other order would orphan them."""
    pattern = candidate_patterns().get(rule)
    if pattern is None:
        return []
    found = [
        row for row in corpus
        if len(row.text.split()) >= MIN_WORDS and usable_text(row.text) and pattern.search(row.text)
    ]
    random.Random(f"{seed}:{rule}").shuffle(found)
    return found


def neighbour(corpus: list[AiRow], row: AiRow, step: int) -> str:
    index = row.line - 1 + step
    if 0 <= index < len(corpus) and corpus[index].document == row.document and corpus[index].source == row.source:
        return corpus[index].text
    return ""


def off_prefix_rules(labels: list[dict], corpus: list[AiRow], seed: int = SEED) -> list[str]:
    """Strict prefix, because a skipped candidate is a hand pick and the seed exists to stop hand picks."""
    drifted = []
    for rule in dict.fromkeys(row["rule"] for row in labels):
        labeled = [row["line"] for row in labels if row["rule"] == rule]
        drawn = [row.line for row in candidates(rule, corpus, seed)[: len(labeled)]]
        if labeled != drawn:
            drifted.append(rule)
    return drifted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rule", choices=sorted(candidate_patterns()))
    parser.add_argument("--count", type=int, default=BATCH)
    arguments = parser.parse_args()
    ai_corpus_digest()
    corpus = load_ai_corpus()
    labels = load_labels()
    drifted = off_prefix_rules(labels, corpus)
    if drifted:
        raise SystemExit(f"labels leave the seeded candidate order for {drifted}")
    found = candidates(arguments.rule, corpus)
    start = sum(1 for row in labels if row["rule"] == arguments.rule)
    print(f"{arguments.rule}: {len(found)} candidates, {start} labeled")
    for row in found[start : start + arguments.count]:
        print(f"[{row.line}] {row.source} doc {row.document}")
        print(f"  < {neighbour(corpus, row, -1)}")
        print(f"  = {row.text}")
        print(f"  > {neighbour(corpus, row, 1)}")


if __name__ == "__main__":
    main()
