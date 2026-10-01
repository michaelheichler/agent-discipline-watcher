#!/usr/bin/env python3
"""Vote with the shipped German exemplars as the only neighbours, because that is the vote a German sentence meets at runtime."""
import json
import math
import random
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from typing import NamedTuple

from ai_corpus_de import ai_corpus_digest, load_ai_corpus, load_labels
from build_pattern_exemplars_de import MANIFEST_PATH, OUTPUT_PATH, REPOSITORY_ROOT, SEED, corpus_digest, load_corpus, usable_text

RECORD_PATH = REPOSITORY_ROOT / "evals" / "qualification_de.json"
NEIGHBOUR_COUNTS = (1, 3, 5, 7)
PRODUCTION_NEIGHBOURS = 5
HUMAN_QUERIES = 40
BATCH_SIZE = 32
WILSON_Z = 1.96
VIOLATING = "violating"
CLEAN = "clean"
HELD_OUT = "held_out_violating"
NEAR_MISS = "near_miss_clean"
HUMAN = "human_clean"
Vector = tuple[float, ...]


class Query(NamedTuple):
    kind: str
    text: str


def _wilson(hits: int, total: int) -> list[float] | None:
    """An interval, because four held-out sentences read as exact and are not."""
    if not total:
        return None
    share = hits / total
    denominator = 1 + WILSON_Z**2 / total
    centre = (share + WILSON_Z**2 / (2 * total)) / denominator
    spread = WILSON_Z * math.sqrt(share * (1 - share) / total + WILSON_Z**2 / (4 * total**2)) / denominator
    return [round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4)]


def votes_violating(vector: Vector, neighbours: list[tuple[str, Vector]], count: int) -> bool:
    """Copied from pattern_semantic, because a spike on another ranking would grade a vote nobody ships."""
    ranked = sorted(neighbours, key=lambda entry: -sum(one * other for one, other in zip(vector, entry[1])))
    return Counter(label for label, _ in ranked[:count]).most_common(1)[0][0] == VIOLATING


def rule_queries(rule_labels: list[dict], texts: dict[int, str], shipped_rows: set[int]) -> list[Query]:
    """Near misses share the trigger and the models, because a vote that only spots machine text flags them too."""
    unshipped = [label for label in rule_labels if label["line"] not in shipped_rows]
    held_out = [Query(HELD_OUT, texts[label["line"]]) for label in unshipped if label["label"] == VIOLATING]
    near_miss = [Query(NEAR_MISS, texts[label["line"]]) for label in unshipped if label["label"] == CLEAN]
    return held_out + near_miss


def human_queries(corpus: Iterable, used_rows: set[int], seed: int = SEED) -> list[Query]:
    """Shared across rules, because a fresh human sample per rule would make the false alarm rates incomparable."""
    pool = [row for row in corpus if row.row not in used_rows and usable_text(row.text)]
    random.Random(f"{seed}:human-queries").shuffle(pool)
    return [Query(HUMAN, row.text) for row in pool[:HUMAN_QUERIES]]


def _rate(flags: list[bool]) -> dict[str, object]:
    hits = sum(flags)
    return {"flagged": hits, "total": len(flags), "rate": round(hits / len(flags), 4) if flags else None,
            "interval": _wilson(hits, len(flags))}


def leave_one_out(neighbours: list[tuple[str, Vector]], count: int) -> dict[str, object]:
    """Split by class, because one accuracy figure hides a vote that flags everything."""
    flags = [
        (label, votes_violating(vector, neighbours[:index] + neighbours[index + 1 :], count))
        for index, (label, vector) in enumerate(neighbours)
    ]
    return {f"{kind}_flagged": _rate([flag for label, flag in flags if label == kind]) for kind in (VIOLATING, CLEAN)}


def score_rule(neighbours: list[tuple[str, Vector]], queries: list[tuple[Query, Vector]], count: int) -> dict[str, object]:
    by_kind = {kind: [votes_violating(vector, neighbours, count) for query, vector in queries if query.kind == kind]
               for kind in (HELD_OUT, NEAR_MISS, HUMAN)}
    return {"neighbours": count, "leave_one_out": leave_one_out(neighbours, count),
            **{kind: _rate(flags) for kind, flags in by_kind.items()}}


def labeled_pool(neighbours: list[tuple[str, Vector]], queries: list[tuple[Query, Vector]]) -> list[tuple[str, Vector]]:
    """Asks whether the model can separate the pattern at all, because four exemplars per side may be too few for any model."""
    labeled = [(VIOLATING if query.kind == HELD_OUT else CLEAN, vector) for query, vector in queries if query.kind != HUMAN]
    return neighbours + labeled


def rule_record(neighbours: list[tuple[str, Vector]], queries: list[tuple[Query, Vector]]) -> dict[str, object]:
    sweep = [score_rule(neighbours, queries, count) for count in NEIGHBOUR_COUNTS]
    pool = labeled_pool(neighbours, queries)
    return {
        "production": next(row for row in sweep if row["neighbours"] == PRODUCTION_NEIGHBOURS), "sweep": sweep,
        "labeled_pool": [{"neighbours": count, **leave_one_out(pool, count)} for count in NEIGHBOUR_COUNTS],
    }


def embed_all(texts: list[str], embed: Callable[[tuple[str, ...]], tuple | None]) -> dict[str, Vector]:
    vectors: dict[str, Vector] = {}
    for start in range(0, len(texts), BATCH_SIZE):
        batch = tuple(texts[start : start + BATCH_SIZE])
        answered = embed(batch)
        if answered is None:
            raise ValueError("no embedding server answered; start it through the ADW lease before measuring")
        vectors.update(zip(batch, (tuple(vector) for vector in answered)))
    return vectors


def measured_queries(exemplars: list[dict]) -> dict[str, list[Query]]:
    """Only rules with a violating side, because a silent rule never votes and has nothing to measure."""
    labels = load_labels()
    texts = {row.line: row.text for row in load_ai_corpus()}
    shipped = {row["row"] for row in exemplars if row["label"] == VIOLATING}
    human = human_queries(load_corpus(), {row["row"] for row in exemplars if row["label"] == CLEAN})
    voted = sorted({row["rule"] for row in exemplars if row["label"] == VIOLATING})
    return {rule: rule_queries([row for row in labels if row["rule"] == rule], texts, shipped) + human for rule in voted}


def measured_rules(exemplars: list[dict], queries: dict[str, list[Query]], vectors: dict[str, Vector]) -> dict[str, object]:
    return {
        rule: rule_record(
            [(row["label"], vectors[row["text"]]) for row in exemplars if row["rule"] == rule],
            [(query, vectors[query.text]) for query in rule_rows],
        )
        for rule, rule_rows in queries.items()
    }


def _client() -> tuple[Callable, Callable]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    from lib import embedding_client
    return embedding_client.embed, embedding_client.embeddings_urls


def main() -> None:
    corpus_digest()
    ai_corpus_digest()
    exemplars = [json.loads(line) for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    queries = measured_queries(exemplars)
    wanted = {row["text"] for row in exemplars} | {query.text for rows in queries.values() for query in rows}
    embed, urls = _client()
    vectors = embed_all(sorted(wanted), embed)
    record = {
        "exemplars_sha256": json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["sha256"],
        "endpoint": (urls() or [""])[0], "neighbour_counts": list(NEIGHBOUR_COUNTS), "human_queries": HUMAN_QUERIES,
        "rules": measured_rules(exemplars, queries, vectors),
    }
    RECORD_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(queries)} rules measured, record at {RECORD_PATH.name}")


if __name__ == "__main__":
    main()
