#!/usr/bin/env python3
"""Accuracy is split by paragraph length, because T-010 reads the stop-word threshold off this table instead of guessing it."""
import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
prose_language = importlib.import_module("lib.prose_language")

DEFAULT_CORPUS = REPOSITORY_ROOT / "evals" / "corpus_paragraphs.jsonl"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "language_detection.json"
BUCKET_STARTS = (1, 4, 8, 16, 32)
DESCRIPTION = (
    "Pass each corpus as LANG=PATH. A row holds a paragraphs list, or a paragraph or text string. "
    "A language field in the row beats the LANG label."
)


class Sample(NamedTuple):
    language: str
    text: str


def corpus_argument(text: str) -> tuple[str, Path]:
    label, separator, path = text.partition("=")
    if not separator or label not in prose_language.LANGUAGES:
        raise argparse.ArgumentTypeError(f"expected LANG=PATH with LANG in {', '.join(prose_language.LANGUAGES)}")
    return label, Path(path)


def _row_texts(row: dict) -> list[str]:
    if isinstance(row.get("paragraphs"), list):
        return [text for text in row["paragraphs"] if isinstance(text, str)]
    text = row.get("paragraph", row.get("text"))
    return [text] if isinstance(text, str) else []


def load_samples(label: str, path: Path) -> list[Sample]:
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if not rows:
        raise ValueError(f"{path}: corpus contains no rows")
    return [Sample(row.get("language", label), text) for row in rows for text in _row_texts(row)]


def bucket_name(words: int) -> str:
    starts = [start for start in BUCKET_STARTS if start <= words]
    if not starts:
        return "0"
    index = BUCKET_STARTS.index(starts[-1])
    if index + 1 == len(BUCKET_STARTS):
        return f"{starts[-1]}+"
    return f"{starts[-1]}-{BUCKET_STARTS[index + 1] - 1}"


def _cell(rows: list[tuple[str | None, str]]) -> dict[str, object]:
    decided = [(found, expected) for found, expected in rows if found is not None]
    correct = sum(found == expected for found, expected in decided)
    return {
        "paragraphs": len(rows),
        "decided": len(decided),
        "correct": correct,
        "accuracy": round(correct / len(rows), 4) if rows else None,
        "decided_accuracy": round(correct / len(decided), 4) if decided else None,
    }


def _table(samples: list[Sample]) -> dict[str, dict[str, list[tuple[str | None, str]]]]:
    table: dict[str, dict[str, list[tuple[str | None, str]]]] = {}
    for sample in samples:
        signal = prose_language.paragraph_signal(sample.text)
        by_bucket = table.setdefault(sample.language, {})
        by_bucket.setdefault(bucket_name(signal.words), []).append((signal.language, sample.language))
    return table


def build_report(corpora: list[tuple[str, Path]], samples: list[Sample]) -> dict[str, object]:
    table = _table(samples)
    return {
        "corpora": {str(path): label for label, path in corpora},
        "min_strong_words": prose_language.MIN_STRONG_WORDS,
        "bucket_starts": list(BUCKET_STARTS),
        "by_language": {
            language: {bucket: _cell(rows) for bucket, rows in sorted(buckets.items())}
            for language, buckets in sorted(table.items())
        },
    }


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("corpora", nargs="*", type=corpus_argument, metavar="LANG=PATH")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parsed = parser.parse_args(argv)
    if not parsed.corpora and DEFAULT_CORPUS.exists():
        parsed.corpora = [("en", DEFAULT_CORPUS)]
    if not parsed.corpora:
        parser.error(f"no corpus given and {DEFAULT_CORPUS} is absent, rebuild it with evals/build_paragraph_corpus.py")
    return parsed


def main(argv: list[str] | None = None) -> None:
    parsed = _arguments(sys.argv[1:] if argv is None else argv)
    samples = [sample for label, path in parsed.corpora for sample in load_samples(label, path)]
    report = build_report(parsed.corpora, samples)
    parsed.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
