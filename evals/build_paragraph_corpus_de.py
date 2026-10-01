#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import dewiki_source
import parquet_source
from build_ai_corpus_de import ASSISTANT, CODE_FENCE_RE, WILDCHAT_DATASET
from build_human_corpus_de import (
    GUTENBERG_DATASET,
    MAX_FOREIGN_RATIO,
    _foreign_ratio,
    _gutenberg_documents,
    _reads_as_german,
)


class DocumentRow(NamedTuple):
    lang: str
    origin: str
    genre: str
    source: str
    document: int
    paragraphs: tuple[str, ...]


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "corpus_paragraphs_de.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_paragraph_manifest_de.json"
HUMAN = "human"
ASSISTANT_ORIGIN = "assistant"
PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")
TERMINATORS = ".!?"
MIN_PARAGRAPH_WORDS = 25
MAX_PARAGRAPH_CHARS = 3000
MIN_PARAGRAPHS_PER_DOCUMENT = 4
PARAGRAPHS_PER_DOCUMENT = 10
DEWIKI_SKIP_ARTICLES = 60000
DOCUMENT_TARGETS = {"encyclopedia": 2500, "literature": 1500, "wildchat": 2500}
COVERAGE_GAP = "No news genre, since the only German machine-written news set reads as one flat line."


def _is_prose_paragraph(text: str) -> bool:
    if not text or len(text) > MAX_PARAGRAPH_CHARS:
        return False
    if text[-1] not in TERMINATORS or not text[0].isupper():
        return False
    if len(text.split()) < MIN_PARAGRAPH_WORDS:
        return False
    if _foreign_ratio(text) > MAX_FOREIGN_RATIO:
        return False
    return _reads_as_german(text)


def paragraphs_of(document: str) -> tuple[str, ...]:
    parts = PARAGRAPH_SPLIT_RE.split(document.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = (" ".join(part.split()) for part in parts)
    return tuple(part for part in cleaned if _is_prose_paragraph(part))


def _dewiki_articles():
    dump_path = dewiki_source.ensure_dump()
    for index, article in enumerate(dewiki_source.iter_articles(dump_path)):
        if index >= DEWIKI_SKIP_ARTICLES:
            yield article


def build_encyclopedia() -> list[DocumentRow]:
    rows: list[DocumentRow] = []
    for article in _dewiki_articles():
        chosen = paragraphs_of(dewiki_source.clean_wikitext(article.wikitext))[:PARAGRAPHS_PER_DOCUMENT]
        if len(chosen) >= MIN_PARAGRAPHS_PER_DOCUMENT:
            rows.append(DocumentRow("de", HUMAN, "encyclopedia", "dewiki-20180920", article.page_id, chosen))
        if len(rows) >= DOCUMENT_TARGETS["encyclopedia"]:
            break
    return rows[: DOCUMENT_TARGETS["encyclopedia"]]


def build_literature() -> list[DocumentRow]:
    rows: list[DocumentRow] = []
    for number, document in _gutenberg_documents():
        chosen = paragraphs_of(document)[:PARAGRAPHS_PER_DOCUMENT]
        if len(chosen) >= MIN_PARAGRAPHS_PER_DOCUMENT:
            rows.append(DocumentRow("de", HUMAN, "literature", GUTENBERG_DATASET, number, chosen))
        if len(rows) >= DOCUMENT_TARGETS["literature"]:
            break
    return rows[: DOCUMENT_TARGETS["literature"]]


def _wildchat_text(row: dict) -> str:
    turns = row.get("conversation")
    if not isinstance(turns, list):
        return ""
    parts = [
        CODE_FENCE_RE.sub(" ", turn["content"])
        for turn in turns
        if isinstance(turn, dict) and turn.get("role") == ASSISTANT and isinstance(turn.get("content"), str)
    ]
    return "\n\n".join(parts)


def build_wildchat() -> list[DocumentRow]:
    rows: list[DocumentRow] = []
    for number, row in parquet_source.wildchat_rows():
        chosen = paragraphs_of(_wildchat_text(row))[:PARAGRAPHS_PER_DOCUMENT]
        if len(chosen) >= MIN_PARAGRAPHS_PER_DOCUMENT:
            rows.append(DocumentRow("de", ASSISTANT_ORIGIN, "wildchat", WILDCHAT_DATASET, number, chosen))
        if len(rows) >= DOCUMENT_TARGETS["wildchat"]:
            break
    return rows[: DOCUMENT_TARGETS["wildchat"]]


GENRE_BUILDERS = {"encyclopedia": build_encyclopedia, "literature": build_literature, "wildchat": build_wildchat}


def serialize(rows: list[DocumentRow]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(dict(row._asdict(), paragraphs=list(row.paragraphs))) + "\n" for row in rows)


def _genre_manifest(genre: str, rows: list[DocumentRow]) -> dict[str, object]:
    mine = [row for row in rows if row.genre == genre]
    counts = Counter(len(row.paragraphs) for row in mine)
    return {
        "documents": len(mine),
        "paragraphs": sum(len(row.paragraphs) for row in mine),
        "paragraphs_per_document": dict(sorted(counts.items())),
    }


def build_manifest(rows: list[DocumentRow], digest: str) -> dict[str, object]:
    return {
        "corpus": OUTPUT_PATH.name,
        "sha256": digest,
        "lang": "de",
        "min_paragraphs_per_document": MIN_PARAGRAPHS_PER_DOCUMENT,
        "paragraphs_per_document": PARAGRAPHS_PER_DOCUMENT,
        "min_paragraph_words": MIN_PARAGRAPH_WORDS,
        "coverage_gap": COVERAGE_GAP,
        "wildchat_revision": parquet_source.WILDCHAT_REVISION,
        "genres": {genre: _genre_manifest(genre, rows) for genre in GENRE_BUILDERS},
    }


def main() -> None:
    rows: list[DocumentRow] = []
    for genre, builder in GENRE_BUILDERS.items():
        built = builder()
        rows.extend(built)
        print(f"{genre}: {len(built)} documents")
    serialized = serialize(rows)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(rows, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{len(rows)} documents, sha256 {digest}")


if __name__ == "__main__":
    main()
