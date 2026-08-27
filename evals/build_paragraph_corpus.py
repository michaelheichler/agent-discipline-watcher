#!/usr/bin/env python3
"""Draws documents that still carry their paragraph breaks, because the sentence corpora flatten every source and no paragraph-shaped rule can be measured against them."""
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "evals"))

# pylint: disable=wrong-import-position
from build_ai_corpus import CODE_FENCE_RE, _cached, _store, _token


class Source(NamedTuple):
    name: str
    origin: str
    dataset: str
    config: str
    field: str
    conversations: tuple[str, ...]
    documents: int
    note: str


class DocumentRow(NamedTuple):
    origin: str
    genre: str
    dataset: str
    document: int
    paragraphs: tuple[str, ...]


OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "corpus_paragraphs.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_paragraph_manifest.json"
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60
REQUEST_PAUSE = 1.0
RETRY_DELAYS = (5.0, 15.0, 45.0, 120.0)
HUMAN = "human"
ASSISTANT = "assistant"
PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
LIST_LINE_RE = re.compile(r"^\s*([-*+>#|]|\d+[.)])\s")
WIKI_HEADING_RE = re.compile(r"^\s*=+.*=+\s*$")
ENGLISH_MARKERS = frozenset({"the", "of", "and", "to", "in", "a", "is", "was", "that", "it"})
WORD_EDGE_CHARS = ".,;:!?\"'()[]"
TERMINATORS = ".!?"
MIN_PARAGRAPH_WORDS = 25
MAX_PARAGRAPH_CHARS = 3000
MAX_FOREIGN_RATIO = 0.01
MIN_PARAGRAPHS_PER_DOCUMENT = 4
PARAGRAPHS_PER_DOCUMENT = 10
COVERAGE_GAP = (
    "No news genre. Every news set reachable here stores an article as one flat line, "
    "so its paragraph breaks are already gone at the source."
)
SOURCES = (
    Source(
        "encyclopedia", HUMAN, "wikimedia/wikipedia", "20231101.en", "text", (), 2500,
        "Present-day expository prose with its section paragraphs intact.",
    ),
    Source(
        "literature", HUMAN, "sedthh/gutenberg_english", "default", "TEXT", (), 2500,
        "Public domain books stored with CRLF paragraph breaks, so the register is mostly pre-1930.",
    ),
    Source(
        "wildchat", ASSISTANT, "allenai/WildChat-4.8M", "default", "", ("conversation",), 2500,
        "Assistant replies to public prompts, code fences removed.",
    ),
    Source(
        "arena", ASSISTANT, "lmarena-ai/arena-human-preference-100k", "default", "",
        ("conversation_a", "conversation_b"), 2500,
        "Assistant replies from a preference arena, code fences removed.",
    ),
)


def _page_url(source: Source, offset: int) -> str:
    query = urllib.parse.urlencode({
        "dataset": source.dataset, "config": source.config, "split": "train",
        "offset": offset, "length": PAGE_SIZE,
    })
    return f"{ROWS_ENDPOINT}?{query}"


def _read_page(url: str) -> dict:
    request = urllib.request.Request(url)
    token = _token()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _fetch(source: Source, offset: int) -> dict:
    """A rate limit mid sweep would otherwise discard every page already paid for."""
    page = _cached(source.dataset, offset)
    if page is not None:
        return page
    url = _page_url(source, offset)
    for delay in RETRY_DELAYS:
        try:
            page = _read_page(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            time.sleep(delay)
            continue
        _store(source.dataset, offset, page)
        return page
    page = _read_page(url)
    _store(source.dataset, offset, page)
    return page


def _foreign_ratio(text: str) -> float:
    return sum(ord(character) > 127 for character in text) / len(text)


def _reads_as_english(text: str) -> bool:
    words = {word.strip(WORD_EDGE_CHARS).lower() for word in text.split()}
    return bool(words & ENGLISH_MARKERS)


def _is_prose_paragraph(text: str) -> bool:
    """Rejects headings, lists and tables because an ending rule measured over them would score markup rather than prose."""
    if not text or len(text) > MAX_PARAGRAPH_CHARS:
        return False
    if LIST_LINE_RE.match(text) or WIKI_HEADING_RE.match(text):
        return False
    if text[-1] not in TERMINATORS or not text[0].isupper():
        return False
    if len(text.split()) < MIN_PARAGRAPH_WORDS:
        return False
    if _foreign_ratio(text) > MAX_FOREIGN_RATIO:
        return False
    return _reads_as_english(text)


def paragraphs_of(document: str) -> tuple[str, ...]:
    parts = PARAGRAPH_SPLIT_RE.split(document.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = (" ".join(part.split()) for part in parts)
    return tuple(part for part in cleaned if _is_prose_paragraph(part))


def _document_texts(row: dict, source: Source) -> list[str]:
    if source.field:
        value = row.get(source.field)
        return [value] if isinstance(value, str) else []
    texts = []
    for field in source.conversations:
        turns = row.get(field)
        if not isinstance(turns, list):
            continue
        texts.extend(
            CODE_FENCE_RE.sub(" ", turn["content"])
            for turn in turns
            if isinstance(turn, dict) and turn.get("role") == ASSISTANT and isinstance(turn.get("content"), str)
        )
    return texts


def _rows_from(row: dict, source: Source, number: int) -> list[DocumentRow]:
    found = []
    for text in _document_texts(row, source):
        chosen = paragraphs_of(text)[:PARAGRAPHS_PER_DOCUMENT]
        if len(chosen) < MIN_PARAGRAPHS_PER_DOCUMENT:
            continue
        found.append(DocumentRow(source.origin, source.name, source.dataset, number, chosen))
    return found


def _total_rows(source: Source) -> int:
    return int(_fetch(source, 0)["num_rows_total"])


def _offsets(total: int, wanted_pages: int) -> list[int]:
    """Strides across the whole set rather than reading the head, because the earliest rows share one author or one model."""
    stride = max(PAGE_SIZE, total // max(wanted_pages, 1))
    return [index * stride for index in range(wanted_pages) if index * stride < total]


def build_source(source: Source) -> list[DocumentRow]:
    total = _total_rows(source)
    rows: list[DocumentRow] = []
    seen: set[str] = set()
    for offset in _offsets(total, max(1, source.documents // 10)):
        for index, entry in enumerate(_fetch(source, offset)["rows"]):
            fresh = [row for row in _rows_from(entry["row"], source, offset + index) if row.paragraphs[0] not in seen]
            seen.update(row.paragraphs[0] for row in fresh)
            rows.extend(fresh)
        print(f"  {source.name}: {len(rows)} documents at offset {offset}", flush=True)
        if len(rows) >= source.documents:
            break
        time.sleep(REQUEST_PAUSE)
    return rows[: source.documents]


def serialize(rows: list[DocumentRow]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(dict(row._asdict(), paragraphs=list(row.paragraphs))) + "\n" for row in rows)


def _source_manifest(source: Source, rows: list[DocumentRow]) -> dict[str, object]:
    mine = [row for row in rows if row.genre == source.name]
    counts = Counter(len(row.paragraphs) for row in mine)
    return {
        "dataset": source.dataset,
        "config": source.config,
        "origin": source.origin,
        "documents": len(mine),
        "paragraphs": sum(len(row.paragraphs) for row in mine),
        "paragraphs_per_document": dict(sorted(counts.items())),
        "note": source.note,
    }


def build_manifest(rows: list[DocumentRow], digest: str) -> dict[str, object]:
    return {
        "corpus": OUTPUT_PATH.name,
        "sha256": digest,
        "min_paragraphs_per_document": MIN_PARAGRAPHS_PER_DOCUMENT,
        "paragraphs_per_document": PARAGRAPHS_PER_DOCUMENT,
        "min_paragraph_words": MIN_PARAGRAPH_WORDS,
        "coverage_gap": COVERAGE_GAP,
        "sources": {source.name: _source_manifest(source, rows) for source in SOURCES},
    }


def main() -> None:
    rows: list[DocumentRow] = []
    for source in SOURCES:
        print(f"{source.name} ({source.dataset})", flush=True)
        rows.extend(build_source(source))
    serialized = serialize(rows)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(rows, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"{len(rows)} documents, sha256 {digest}")


if __name__ == "__main__":
    main()
