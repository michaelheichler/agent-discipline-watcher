#!/usr/bin/env python3
import csv
import json
import statistics
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TypedDict


class CorpusRow(TypedDict):
    label: str
    source: str
    bias: str
    text: str


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = Path.home() / "Downloads"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "hooks" / "lib"
SENTENCE_SOURCE_NAME = "ai_vs_human_text.csv"
DOCUMENT_SOURCE_NAME = "AI Generated Essays Dataset.csv"
# WHY: AI p90 is 57 words and human p10 is 174, so word count alone separates the labels.
NONOVERLAPPING_SOURCE_NAME = "data_for_preprocessing.csv"
# WHY: Every row is placeholder text, and Human rows claim to demonstrate AI generated style.
PLACEHOLDER_SOURCE_NAME = "large_ai_human_dataset.csv"
SENTENCE_OUTPUT_NAME = "corpus_slop_sentence.jsonl"
DOCUMENT_OUTPUT_NAME = "corpus_slop_document.jsonl"
SENTENCE_BIAS = "Human class is famous aphorisms, not ordinary prose."
DOCUMENT_BIAS = "Student persuasive essays only."
DOCUMENT_MIN_WORDS = 150
DOCUMENT_MAX_WORDS = 450
# WHY: Wrapped AI rows and unwrapped human rows separate the labels on one character at AUC 0.9457.
WRAPPING_QUOTES = ('"', "'")
# WHY: A perfect one-to-one length match still leaves word count at AUC 0.7994, one fixed length gives 0.5.
DOCUMENT_TRUNCATE_WORDS = 228
# WHY: Truncation cuts document endings, so a closer rule scored here measures the cut.
DOCUMENT_TRUNCATION_NOTE = "Truncated to a fixed word count, so endings are absent."
# WHY: A leak above this is indistinguishable from the 0.963 marker signal being measured.
MAX_LEAK_AUC = 0.60
SOURCE_NAMES = (
    SENTENCE_SOURCE_NAME,
    DOCUMENT_SOURCE_NAME,
    NONOVERLAPPING_SOURCE_NAME,
    PLACEHOLDER_SOURCE_NAME,
)
REJECTED_SOURCE_NAMES = frozenset(
    {NONOVERLAPPING_SOURCE_NAME, PLACEHOLDER_SOURCE_NAME}
)
OUTPUT_NAMES: Mapping[str, str] = {
    SENTENCE_SOURCE_NAME: SENTENCE_OUTPUT_NAME,
    DOCUMENT_SOURCE_NAME: DOCUMENT_OUTPUT_NAME,
}
DOCUMENT_LABELS: Mapping[str, str] = {"0": "human", "1": "ai"}
CsvRow = Mapping[str, str | None]


def _required_row(location: str, row: CsvRow, required_fields: Sequence[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in required_fields:
        value = row.get(field)
        if value is None or not value.strip():
            raise ValueError(
                f"{location} has no value for required field {field!r}"
            )
        values[field] = value
    return values


def _read_csv(source_path: Path, required_fields: Sequence[str]) -> list[dict[str, str]]:
    with source_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError(f"{source_path}: CSV header is missing")
        missing = tuple(field for field in required_fields if field not in fieldnames)
        if missing:
            raise ValueError(
                f"{source_path}: CSV header is missing required fields {missing!r}"
            )
        rows = [
            _required_row(f"{source_path}: row {number}", row, required_fields)
            for number, row in enumerate(reader, start=2)
        ]
    if not rows:
        raise ValueError(f"{source_path}: CSV contains no data rows")
    return rows


def _validate_labels(location: str, actual: set[str], labels: Sequence[str]) -> None:
    allowed = set(labels)
    invalid = actual - allowed
    missing = allowed - actual
    if invalid:
        raise ValueError(f"{location} has invalid labels {invalid!r}")
    if missing:
        raise ValueError(f"{location} is missing labels {missing!r}")


def _word_count(text: str) -> int:
    return len(text.split())


def _normalize_text(text: str) -> str:
    """Strip only a matched wrapping pair, because a lone leading quote is a title the author wrote."""
    cleaned = text.strip()
    while len(cleaned) >= 2 and cleaned[0] in WRAPPING_QUOTES and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _leading_quote_auc(rows: Sequence[CorpusRow]) -> float:
    return _label_auc(rows, lambda row: float(row["text"][:1] in WRAPPING_QUOTES))


def _word_count_auc(rows: Sequence[CorpusRow]) -> float:
    return _label_auc(rows, lambda row: float(_word_count(row["text"])))


def _label_auc(rows: Sequence[CorpusRow], score: Callable[[CorpusRow], float]) -> float:
    """Reported as distance from a coin flip, because a feature that runs backwards leaks exactly as hard."""
    ai_scores = sorted(score(row) for row in rows if row["label"] == "ai")
    human_scores = sorted(score(row) for row in rows if row["label"] == "human")
    if not ai_scores or not human_scores:
        raise ValueError("Cannot measure a label leak without rows on both sides")
    wins = sum(
        sum((generated > written) + 0.5 * (generated == written) for written in human_scores)
        for generated in ai_scores
    )
    return abs(wins / (len(ai_scores) * len(human_scores)) - 0.5) + 0.5


def _sort_rows(rows: Sequence[CorpusRow]) -> list[CorpusRow]:
    return sorted(
        rows,
        key=lambda row: (row["label"], row["source"], row["bias"], row["text"]),
    )


def build_sentence_rows(source_path: Path) -> list[CorpusRow]:
    raw_rows = _read_csv(source_path, ("id", "text", "label"))
    actual_labels = {row["label"] for row in raw_rows}
    _validate_labels(f"{source_path}: field 'label'", actual_labels, ("ai", "human"))
    rows: list[CorpusRow] = [
        {
            "label": row["label"],
            "source": source_path.name,
            "bias": SENTENCE_BIAS,
            "text": _normalize_text(row["text"]),
        }
        for row in raw_rows
    ]
    sorted_rows = _sort_rows(_deduplicated(rows))
    _reject_leaks(SENTENCE_OUTPUT_NAME, sorted_rows)
    return sorted_rows


def _document_row(source_path: Path, raw_row: Mapping[str, str]) -> CorpusRow:
    return {
        "label": DOCUMENT_LABELS[raw_row["generated"]],
        "source": source_path.name,
        "bias": DOCUMENT_BIAS,
        "text": _normalize_text(raw_row["text"]),
    }


def _truncated(row: CorpusRow) -> CorpusRow:
    return {
        "label": row["label"],
        "source": row["source"],
        "bias": row["bias"] + " " + DOCUMENT_TRUNCATION_NOTE,
        "text": " ".join(row["text"].split()[:DOCUMENT_TRUNCATE_WORDS]),
    }


def _deduplicated(rows: Sequence[CorpusRow]) -> list[CorpusRow]:
    """Dropped because a repeated essay counts its own features twice and inflates any measurement taken here."""
    seen: set[str] = set()
    unique: list[CorpusRow] = []
    for row in rows:
        if row["text"] in seen:
            continue
        seen.add(row["text"])
        unique.append(row)
    return unique


def _balanced(rows: Sequence[CorpusRow]) -> list[CorpusRow]:
    """Sorts before it slices, because otherwise the surviving rows depend on the order the CSV happened to use."""
    ordered = _sort_rows(rows)
    ai_rows = [row for row in ordered if row["label"] == "ai"]
    human_rows = [row for row in ordered if row["label"] == "human"]
    keep = min(len(ai_rows), len(human_rows))
    if not keep:
        raise ValueError("Document corpus needs rows on both sides after truncation")
    return _sort_rows((*ai_rows[:keep], *human_rows[:keep]))


def _length_match_documents(rows: Sequence[CorpusRow]) -> list[CorpusRow]:
    """Truncates rather than selects, because the human pool has no row under 250 words while AI has 11."""
    long_enough = [
        row for row in rows if _word_count(row["text"]) >= DOCUMENT_TRUNCATE_WORDS
    ]
    truncated = _deduplicated([_truncated(row) for row in long_enough])
    return _balanced(truncated)


def _reject_leaks(name: str, rows: Sequence[CorpusRow]) -> None:
    """Raises rather than warns, because a leaking corpus produces a precision figure that reads as valid."""
    for label, measured in (
        ("leading quote", _leading_quote_auc(rows)),
        ("word count", _word_count_auc(rows)),
    ):
        if measured > MAX_LEAK_AUC:
            raise ValueError(
                f"{name}: {label} separates the labels at AUC {measured:.4f}, "
                f"above the {MAX_LEAK_AUC} ceiling, so every metric scored here would measure it"
            )


def build_document_rows(source_path: Path) -> list[CorpusRow]:
    raw_rows = _read_csv(source_path, ("text", "generated"))
    generated_labels = {row["generated"] for row in raw_rows}
    _validate_labels(f"{source_path}: field 'generated'", generated_labels, ("0", "1"))
    rows = [_document_row(source_path, row) for row in raw_rows]
    banded_rows = [
        row
        for row in rows
        if DOCUMENT_MIN_WORDS <= _word_count(row["text"]) <= DOCUMENT_MAX_WORDS
    ]
    banded_labels = {row["label"] for row in banded_rows}
    if banded_labels != {"ai", "human"}:
        raise ValueError(
            f"{source_path}: 150 to 450 word band must contain both labels, found {banded_labels!r}"
        )
    matched_rows = _length_match_documents(banded_rows)
    _reject_leaks(DOCUMENT_OUTPUT_NAME, matched_rows)
    return matched_rows


BUILDERS: Mapping[str, Callable[[Path], list[CorpusRow]]] = {
    SENTENCE_SOURCE_NAME: build_sentence_rows,
    DOCUMENT_SOURCE_NAME: build_document_rows,
}


def serialize_corpus(rows: Sequence[CorpusRow]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row) + "\n" for row in _sort_rows(rows))


def write_corpus(output_path: Path, rows: Sequence[CorpusRow]) -> None:
    output_path.write_text(serialize_corpus(rows), encoding="utf-8", newline="\n")


def build_corpora(source_directory: Path, output_directory: Path) -> dict[str, list[CorpusRow]]:
    corpora: dict[str, list[CorpusRow]] = {}
    for source_name in SOURCE_NAMES:
        if source_name in REJECTED_SOURCE_NAMES:
            continue
        rows = BUILDERS[source_name](source_directory / source_name)
        output_name = OUTPUT_NAMES[source_name]
        write_corpus(output_directory / output_name, rows)
        corpora[output_name] = rows
    return corpora


def _label_summary(rows: Sequence[CorpusRow], label: str) -> tuple[int, float]:
    lengths = [_word_count(row["text"]) for row in rows if row["label"] == label]
    return len(lengths), statistics.median(lengths)


def _print_summary(output_name: str, rows: Sequence[CorpusRow]) -> None:
    ai_count, ai_median = _label_summary(rows, "ai")
    human_count, human_median = _label_summary(rows, "human")
    print(
        f"{output_name}: ai={ai_count}, ai_median={ai_median:g}, "
        f"human={human_count}, human_median={human_median:g}"
    )


def main() -> None:
    corpora = build_corpora(SOURCE_DIRECTORY, OUTPUT_DIRECTORY)
    for output_name, rows in corpora.items():
        _print_summary(output_name, rows)


if __name__ == "__main__":
    main()
