#!/usr/bin/env python3
"""Pairs each rule against its own clean class, because a single exemplar cosine measured topic and caught 1 sentence in 273."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.scanner import scan_all
from lib.slop_harness import _rule_scopes

HUMAN_CORPUS = REPOSITORY_ROOT / "evals" / "corpus_human_sentences.jsonl"
AI_CORPUS = REPOSITORY_ROOT / "evals" / "corpus_ai_sentences.jsonl"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "benchmark_patterns.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "benchmark_manifest.json"
SAMPLE_NAME = "sample.md"
MINIMUM_ROWS = 30
MAX_ROWS_PER_CLASS = 300
HELD_OUT_SHARE = 2
UNMEASURABLE_NOTE = f"Fewer than {MINIMUM_ROWS} rows on one side, so no precision measured here would mean anything."


class Sample(NamedTuple):
    text: str
    origin: str
    rules: frozenset[str]


class Row(NamedTuple):
    rule: str
    label: str
    split: str
    origin: str
    text: str


def _hashed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:2], "big")


def _split_of(text: str) -> str:
    """Splits by content hash rather than by position, because the same sentence must land on the same side on every rebuild."""
    return "held_out" if _hashed(text) % HELD_OUT_SHARE == 0 else "development"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"{path}: rebuild it before building the benchmark")
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _human_texts() -> list[tuple[str, str]]:
    return [(row["text"], f"human/{row['genre']}") for row in _read_jsonl(HUMAN_CORPUS)]


def _ai_texts() -> list[tuple[str, str]]:
    """Kept because a rule that names an AI tell fired zero times on 60000 human sentences and had no violating class at all."""
    return [(row["text"], f"assistant/{row['source']}") for row in _read_jsonl(AI_CORPUS)]


def _sampled(texts: list[tuple[str, str]]) -> list[Sample]:
    seen: set[str] = set()
    samples: list[Sample] = []
    for text, origin in texts:
        if text in seen:
            continue
        seen.add(text)
        samples.append(Sample(text, origin, frozenset(f["rule"] for f in scan_all(SAMPLE_NAME, text, {}))))
    return samples


def _ordered(samples: list[Sample]) -> list[Sample]:
    return sorted(samples, key=lambda sample: _hashed(sample.text))


def _rows_for(rule: str, positives: list[Sample], negatives: list[Sample]) -> list[Row]:
    chosen = [(sample, "violating") for sample in positives[:MAX_ROWS_PER_CLASS]]
    chosen.extend((sample, "clean") for sample in negatives[:MAX_ROWS_PER_CLASS])
    return [
        Row(rule, label, _split_of(sample.text), sample.origin, sample.text)
        for sample, label in chosen
    ]


def _counts(rows: list[Row]) -> dict[str, int]:
    tally = Counter(f"{row.split}_{row.label}" for row in rows)
    return {key: tally[key] for key in ("development_violating", "development_clean", "held_out_violating", "held_out_clean")}


def _measurable(rows: list[Row]) -> bool:
    counts = _counts(rows)
    return all(counts[key] >= MINIMUM_ROWS // HELD_OUT_SHARE for key in counts)


def _named_rules(samples: list[Sample]) -> list[str]:
    """Unions the observed rules with the harness map because the map misses 8 rules the scanner emits, banned_adverb among them."""
    observed = {rule for sample in samples for rule in sample.rules}
    return sorted(observed | set(_rule_scopes()))


def _balanced_clean(samples: list[Sample]) -> list[Sample]:
    """Draws the clean side from both origins because a human-only clean class lets provenance stand in for the pattern."""
    human = [sample for sample in samples if not sample.rules and sample.origin.startswith("human/")]
    assistant = [sample for sample in samples if not sample.rules and sample.origin.startswith("assistant/")]
    paired = [sample for pair in zip(human, assistant) for sample in pair]
    return paired or human or assistant


def build(samples: list[Sample]) -> tuple[list[Row], dict[str, str]]:
    clean = _balanced_clean(samples)
    rows: list[Row] = []
    rejected: dict[str, str] = {}
    for rule in _named_rules(samples):
        positives = [sample for sample in samples if rule in sample.rules]
        candidate = _rows_for(rule, positives, clean)
        if _measurable(candidate):
            rows.extend(candidate)
            continue
        rejected[rule] = f"{len(positives)} violating rows found. {UNMEASURABLE_NOTE}"
    return rows, rejected


def serialize(rows: list[Row]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row._asdict()) + "\n" for row in rows)


def _rule_manifest(rows: list[Row]) -> dict[str, dict]:
    rules: dict[str, dict] = {}
    for rule in sorted({row.rule for row in rows}):
        mine = [row for row in rows if row.rule == rule]
        violating = Counter(row.origin for row in mine if row.label == "violating")
        clean = Counter(row.origin for row in mine if row.label == "clean")
        rules[rule] = {
            "counts": _counts(mine),
            "violating_origins": dict(sorted(violating.items())),
            "clean_origins": dict(sorted(clean.items())),
        }
    return rules


def build_manifest(rows: list[Row], rejected: dict[str, str], digest: str) -> dict[str, object]:
    return {
        "benchmark": OUTPUT_PATH.name,
        "sha256": digest,
        "minimum_rows": MINIMUM_ROWS,
        "max_rows_per_class": MAX_ROWS_PER_CLASS,
        "measurable_rules": _rule_manifest(rows),
        "unmeasurable_rules": rejected,
    }


def main() -> None:
    samples = _ordered(_sampled(_human_texts() + _ai_texts()))
    rows, rejected = build(samples)
    serialized = serialize(rows)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(rows, rejected, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"{len({row.rule for row in rows})} measurable rules, {len(rejected)} unmeasurable, {len(rows)} rows")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
