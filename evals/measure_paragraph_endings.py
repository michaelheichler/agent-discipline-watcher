#!/usr/bin/env python3
"""The threshold is read off real documents rather than chosen, because a hand-picked cut for a paragraph rule is how the last one reached 0.0000 precision."""
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean, quantiles
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.prose_structure import SENTENCE_BREAK_RE, WORD_RE

CORPUS_PATH = REPOSITORY_ROOT / "evals" / "corpus_paragraphs.jsonl"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "paragraph_endings.json"
HUMAN = "human"
MIN_SENTENCES_PER_PARAGRAPH = 2
MIN_MEASURABLE_PARAGRAPHS = 3
PUNCHY_PERCENTILE = 25
SHARE_PERCENTILES = (90, 95, 99)


class Document(NamedTuple):
    origin: str
    genre: str
    paragraphs: tuple[str, ...]


def load_documents() -> tuple[Document, ...]:
    with CORPUS_PATH.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if not rows:
        raise ValueError(f"{CORPUS_PATH}: corpus contains no rows, rebuild it first")
    return tuple(Document(row["origin"], row["genre"], tuple(row["paragraphs"])) for row in rows)


def _sentence_lengths(paragraph: str) -> list[int]:
    parts = (part.strip() for part in SENTENCE_BREAK_RE.split(paragraph))
    return [count for count in (len(WORD_RE.findall(part)) for part in parts) if count]


def ending_ratio(paragraph: str) -> float | None:
    """A paragraph is compared against its own mean because absolute word counts differ by genre and would import that difference into the rule."""
    lengths = _sentence_lengths(paragraph)
    if len(lengths) < MIN_SENTENCES_PER_PARAGRAPH:
        return None
    average = fmean(lengths)
    return lengths[-1] / average if average else None


def document_ratios(document: Document) -> list[float]:
    found = [ending_ratio(paragraph) for paragraph in document.paragraphs]
    return [ratio for ratio in found if ratio is not None]


def punchy_share(ratios: list[float], cut: float) -> float | None:
    if len(ratios) < MIN_MEASURABLE_PARAGRAPHS:
        return None
    return sum(ratio <= cut for ratio in ratios) / len(ratios)


def _percentile(values: list[float], percentile: int) -> float:
    ordered = quantiles(sorted(values), n=100, method="inclusive")
    return round(ordered[percentile - 1], 4)


def _shares(documents: tuple[Document, ...], cut: float) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for document in documents:
        share = punchy_share(document_ratios(document), cut)
        if share is None:
            continue
        grouped.setdefault(document.origin, []).append(share)
        grouped.setdefault(f"{document.origin}/{document.genre}", []).append(share)
    return grouped


def _rates(grouped: dict[str, list[float]], limit: float) -> dict[str, object]:
    return {
        name: {
            "documents": len(shares),
            "hits": sum(share > limit for share in shares),
            "rate": round(sum(share > limit for share in shares) / len(shares), 5),
        }
        for name, shares in sorted(grouped.items())
    }


def build_report(documents: tuple[Document, ...]) -> dict[str, object]:
    human_ratios = [ratio for document in documents if document.origin == HUMAN for ratio in document_ratios(document)]
    cut = _percentile(human_ratios, PUNCHY_PERCENTILE)
    grouped = _shares(documents, cut)
    human_shares = grouped.get(HUMAN, [])
    return {
        "corpus": CORPUS_PATH.name,
        "documents": len(documents),
        "genres": dict(Counter(f"{row.origin}/{row.genre}" for row in documents)),
        "punchy_ratio_cut": cut,
        "punchy_ratio_percentile": PUNCHY_PERCENTILE,
        "human_ending_ratios": len(human_ratios),
        "candidate_limits": {
            str(percentile): {
                "share_limit": _percentile(human_shares, percentile),
                "by_origin": _rates(grouped, _percentile(human_shares, percentile)),
            }
            for percentile in SHARE_PERCENTILES
        },
    }


def main() -> None:
    report = build_report(load_documents())
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
