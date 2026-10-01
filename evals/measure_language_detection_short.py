#!/usr/bin/env python3
"""Short paragraph prefixes are scored here, because T-010 (Q18) needs the shortest MIN_STRONG_WORDS that still holds."""
import importlib
import json
import random
import sys
from pathlib import Path

import measure_language_detection

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "language_detection_short.json"
DEFAULT_CORPORA = (
    ("en", REPOSITORY_ROOT / "evals" / "corpus_paragraphs.jsonl"),
    ("de", REPOSITORY_ROOT / "evals" / "corpus_paragraphs_de.jsonl"),
)
WORD_COUNTS = (2, 3, 4, 5, 6, 8, 10, 12, 16)
SAMPLE_SIZE = 5000
SEED = 20261001

Pair = tuple[str, str]
MaybePair = tuple[str | None, str]
CorpusEntry = tuple[str, Path]


def _prose_language():
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    return importlib.import_module("lib.prose_language")


def truncate_words(prose, text: str, count: int) -> str | None:
    """None is returned below count words, because a short paragraph cannot stand in for a longer one."""
    cleaned = prose.countable_text(text)
    matches = list(prose.WORD_RE.finditer(cleaned))
    if len(matches) < count:
        return None
    return cleaned[: matches[count - 1].end()]


def eligible_pairs(prose, samples: list, max_count: int) -> list[Pair]:
    pairs = []
    for sample in samples:
        if truncate_words(prose, sample.text, max_count) is not None:
            pairs.append((sample.language, sample.text))
    return pairs


def draw_sample(pairs: list[Pair], size: int, seed: int) -> list[Pair]:
    rng = random.Random(seed)
    return rng.sample(pairs, min(size, len(pairs)))


def _cell(rows: list[MaybePair]) -> dict[str, object]:
    total = len(rows)
    decided = [(found, expected) for found, expected in rows if found is not None]
    correct = sum(found == expected for found, expected in decided)
    return {
        "paragraphs": total,
        "decided": len(decided),
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "undecided_share": round((total - len(decided)) / total, 4) if total else None,
        "decided_accuracy": round(correct / len(decided), 4) if decided else None,
    }


def score_language(prose, drawn: list[Pair]) -> dict[str, object]:
    by_count = {}
    for count in WORD_COUNTS:
        rows = []
        for expected, text in drawn:
            truncated = truncate_words(prose, text, count)
            signal = prose.paragraph_signal(truncated)
            rows.append((signal.language, expected))
        by_count[str(count)] = _cell(rows)
    return by_count


def build_report(prose, corpora: list[CorpusEntry]) -> dict[str, object]:
    by_language = {}
    drawn_sizes = {}
    for label, path in corpora:
        samples = measure_language_detection.load_samples(label, path)
        pairs = eligible_pairs(prose, samples, max(WORD_COUNTS))
        drawn = draw_sample(pairs, SAMPLE_SIZE, SEED)
        drawn_sizes[label] = len(drawn)
        by_language[label] = score_language(prose, drawn)
    return {
        "corpora": {str(path): label for label, path in corpora},
        "seed": SEED,
        "sample_size": SAMPLE_SIZE,
        "drawn_sizes": drawn_sizes,
        "word_counts": list(WORD_COUNTS),
        "by_language": by_language,
    }


def main() -> None:
    prose = _prose_language()
    report = build_report(prose, list(DEFAULT_CORPORA))
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
