#!/usr/bin/env python3
import csv
import hashlib
import json
import re
from collections.abc import Container, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TypedDict


class SentenceRow(TypedDict):
    genre: str
    source: str
    document: int
    text: str


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = Path.home() / "Downloads" / "humanwrittentext"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_sentences.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_manifest.json"
GENRE_SOURCES: Mapping[str, str] = {
    "news": "CNN_DailyMail.csv",
    "encyclopedia": "Wikipedia.csv",
    "literature": "Gutenberg.csv",
}
GENRE_NOTES: Mapping[str, str] = {
    "news": "Rows were scraped with ' . ' standing in for line breaks, so bylines and datelines split into fragments.",
    "encyclopedia": "Present-day expository prose, and the only genre here carrying citation and markup residue.",
    "literature": "Public domain books, mostly published before 1930 with a few modern exceptions, so the register is not contemporary.",
}
REJECTED_SOURCE_NAMES = ("Human.csv", "Shuffled_Human.csv")
REJECTION_NOTE = "A concatenation of Wikipedia.csv and Gutenberg.csv, so reading it would count the same sentences twice."
COVERAGE_GAP = "No technical or software prose in any genre, which is most of what the watcher actually scans."
SENTENCES_PER_GENRE = 20000
SENTENCES_PER_DOCUMENT = 12
MIN_SENTENCE_CHARS = 40
MAX_SENTENCE_CHARS = 300
MIN_SENTENCE_WORDS = 8
MAX_FOREIGN_RATIO = 0.01
TERMINATORS = ".!?"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WORD_EDGE_CHARS = ".,;:!?\"'()[]"
ENGLISH_MARKERS = frozenset({"the", "of", "and", "to", "in", "a", "is", "was", "that", "it"})
# WHY: Gutenberg stores a whole book in one field, far past the 128k default.
MAX_CSV_FIELD_BYTES = 10**9


def _reads_as_english(text: str) -> bool:
    """Filters on function words because Gutenberg carries French and Spanish books that no English rule should be scored against."""
    words = {word.strip(WORD_EDGE_CHARS).lower() for word in text.split()}
    return bool(words & ENGLISH_MARKERS)


def _foreign_ratio(text: str) -> float:
    return sum(ord(character) > 127 for character in text) / len(text)


def _is_usable(text: str) -> bool:
    if not MIN_SENTENCE_CHARS <= len(text) <= MAX_SENTENCE_CHARS:
        return False
    if text[-1] not in TERMINATORS or not text[0].isupper():
        return False
    if len(text.split()) < MIN_SENTENCE_WORDS:
        return False
    if _foreign_ratio(text) > MAX_FOREIGN_RATIO:
        return False
    return _reads_as_english(text)


def _sentences(document: str) -> list[str]:
    parts = (part.strip() for part in SENTENCE_SPLIT_RE.split(document))
    return [part for part in parts if _is_usable(part)]


def _spread(sentences: Sequence[str], quota: int) -> list[str]:
    """Strides through the document rather than taking its head, because a document opens on titles and bylines."""
    if len(sentences) <= quota:
        return list(sentences)
    return list(sentences[:: len(sentences) // quota])[:quota]


def _fresh_texts(document: str, seen: Container[str]) -> list[str]:
    return [
        text
        for text in _spread(_sentences(document), SENTENCES_PER_DOCUMENT)
        if text not in seen
    ]


def _require_text_column(source_path: Path, fieldnames: Sequence[str] | None) -> None:
    if fieldnames is None or "Text" not in fieldnames:
        raise ValueError(f"{source_path}: CSV header must carry a Text column")


def _documents(source_path: Path) -> Iterator[tuple[int, str]]:
    with source_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        _require_text_column(source_path, reader.fieldnames)
        yield from (
            (number, row["Text"])
            for number, row in enumerate(reader, start=2)
            if row.get("Text")
        )


def build_genre(genre: str, source_path: Path) -> list[SentenceRow]:
    rows: list[SentenceRow] = []
    seen: set[str] = set()
    for number, document in _documents(source_path):
        texts = _fresh_texts(document, seen)
        seen.update(texts)
        rows.extend(
            SentenceRow(genre=genre, source=source_path.name, document=number, text=text)
            for text in texts
        )
        if len(rows) >= SENTENCES_PER_GENRE:
            break
    if len(rows) < SENTENCES_PER_GENRE:
        raise ValueError(
            f"{source_path}: yielded {len(rows)} usable sentences, "
            f"below the {SENTENCES_PER_GENRE} the corpus asks for"
        )
    return rows[:SENTENCES_PER_GENRE]


def build_corpus(source_directory: Path) -> dict[str, list[SentenceRow]]:
    return {
        genre: build_genre(genre, source_directory / source_name)
        for genre, source_name in GENRE_SOURCES.items()
    }


def serialize_corpus(corpus: Mapping[str, Sequence[SentenceRow]]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lines = (encoder.encode(row) for genre in GENRE_SOURCES for row in corpus[genre])
    return "".join(line + "\n" for line in lines)


def _genre_manifest(genre: str, rows: Sequence[SentenceRow]) -> dict[str, str | int]:
    return {
        "source": GENRE_SOURCES[genre],
        "sentences": len(rows),
        "documents": len({row["document"] for row in rows}),
        "note": GENRE_NOTES[genre],
    }


def build_manifest(corpus: Mapping[str, Sequence[SentenceRow]], digest: str) -> dict[str, object]:
    return {
        "corpus": OUTPUT_PATH.name,
        "sha256": digest,
        "sentences_per_genre": SENTENCES_PER_GENRE,
        "sentences_per_document": SENTENCES_PER_DOCUMENT,
        "coverage_gap": COVERAGE_GAP,
        "rejected_sources": {name: REJECTION_NOTE for name in REJECTED_SOURCE_NAMES},
        "genres": {genre: _genre_manifest(genre, rows) for genre, rows in corpus.items()},
    }


def main() -> None:
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    corpus = build_corpus(SOURCE_DIRECTORY)
    serialized = serialize_corpus(corpus)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(corpus, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for genre, rows in corpus.items():
        documents = len({row["document"] for row in rows})
        print(f"{genre}: {len(rows)} sentences from {documents} documents")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
