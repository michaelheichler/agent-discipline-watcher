#!/usr/bin/env python3
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Container, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TypedDict

import dewiki_source


class SentenceRow(TypedDict):
    genre: str
    lang: str
    source: str
    document: int
    text: str


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_sentences_de.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_manifest_de.json"
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
CACHE_ROOT = Path.home() / ".adw" / "cache" / "datasets"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60
REQUEST_PAUSE = 0.2
RETRY_DELAYS = (5.0, 15.0, 45.0, 120.0)
GUTENBERG_DATASET = "sedthh/gutenberg_multilang"
GUTENBERG_LANGUAGE = "de"
GENRE_TARGETS: Mapping[str, int] = {"encyclopedia": 20000, "literature": 8000}
SENTENCES_PER_DOCUMENT = 12
DEWIKI_SKIP_ARTICLES = 20000
MIN_SENTENCE_CHARS = 40
MAX_SENTENCE_CHARS = 300
MIN_SENTENCE_WORDS = 8
MAX_FOREIGN_RATIO = 0.04
TERMINATORS = ".!?"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WORD_EDGE_CHARS = ".,;:!?\"'()[]„“”"
GERMAN_MARKERS = frozenset(
    {"der", "die", "das", "und", "ist", "mit", "für", "nicht", "sich", "auf", "ein", "eine", "den", "dem", "von", "zu", "im", "am"}
)
GENRE_NOTES: Mapping[str, str] = {
    "encyclopedia": "German Wikipedia articles from a 2018 dump, present-day expository prose with markup residue.",
    "literature": "German books in the public domain, drawn from a multilingual Gutenberg mirror.",
}
COVERAGE_GAP = "No news or technical prose in either genre, which is most of what the watcher actually scans."


def _foreign_ratio(text: str) -> float:
    return sum(ord(character) > 127 for character in text) / len(text)


def _reads_as_german(text: str) -> bool:
    words = {word.strip(WORD_EDGE_CHARS).lower() for word in text.split()}
    return bool(words & GERMAN_MARKERS)


def _is_usable(text: str) -> bool:
    if not MIN_SENTENCE_CHARS <= len(text) <= MAX_SENTENCE_CHARS:
        return False
    if text[-1] not in TERMINATORS or not text[0].isupper():
        return False
    if len(text.split()) < MIN_SENTENCE_WORDS:
        return False
    if _foreign_ratio(text) > MAX_FOREIGN_RATIO:
        return False
    return _reads_as_german(text)


def _sentences(document: str) -> list[str]:
    parts = (part.strip() for part in SENTENCE_SPLIT_RE.split(document))
    return [part for part in parts if _is_usable(part)]


def _spread(sentences: Sequence[str], quota: int) -> list[str]:
    if len(sentences) <= quota:
        return list(sentences)
    return list(sentences[:: len(sentences) // quota])[:quota]


def _fresh_texts(document: str, seen: Container[str]) -> list[str]:
    return [
        text
        for text in _spread(_sentences(document), SENTENCES_PER_DOCUMENT)
        if text not in seen
    ]


def _cache_path(dataset: str, offset: int) -> Path:
    return CACHE_ROOT / dataset.replace("/", "--") / f"{offset}.json"


def _cached(dataset: str, offset: int) -> dict | None:
    path = _cache_path(dataset, offset)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _store(dataset: str, offset: int, page: dict) -> None:
    path = _cache_path(dataset, offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page), encoding="utf-8")


def _page_url(dataset: str, offset: int) -> str:
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": "default", "split": "train", "offset": offset, "length": PAGE_SIZE}
    )
    return f"{ROWS_ENDPOINT}?{query}"


def _read_page(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _attempt_page(url: str, delay: float) -> dict | None:
    try:
        return _read_page(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        time.sleep(delay)
        return None


def _fetch(dataset: str, offset: int) -> dict:
    page = _cached(dataset, offset)
    if page is not None:
        return page
    url = _page_url(dataset, offset)
    for delay in RETRY_DELAYS:
        page = _attempt_page(url, delay)
        if page is not None:
            _store(dataset, offset, page)
            return page
    page = _read_page(url)
    _store(dataset, offset, page)
    return page


def _total_rows(dataset: str) -> int:
    return int(_fetch(dataset, 0)["num_rows_total"])


def _german_rows(page: dict) -> Iterator[tuple[int, str]]:
    for entry in page["rows"]:
        row = entry["row"]
        meta = json.loads(row["METADATA"])
        if meta.get("language") == GUTENBERG_LANGUAGE:
            yield entry["row_idx"], row["TEXT"]


def _gutenberg_documents() -> Iterator[tuple[int, str]]:
    total = _total_rows(GUTENBERG_DATASET)
    offset = 0
    while offset < total:
        yield from _german_rows(_fetch(GUTENBERG_DATASET, offset))
        offset += PAGE_SIZE
        time.sleep(REQUEST_PAUSE)


def build_literature() -> list[SentenceRow]:
    rows: list[SentenceRow] = []
    seen: set[str] = set()
    for number, document in _gutenberg_documents():
        texts = _fresh_texts(document, seen)
        seen.update(texts)
        rows.extend(
            SentenceRow(genre="literature", lang="de", source=GUTENBERG_DATASET, document=number, text=text)
            for text in texts
        )
        if len(rows) >= GENRE_TARGETS["literature"]:
            break
    return rows[: GENRE_TARGETS["literature"]]


def _dewiki_articles() -> Iterator[dewiki_source.Article]:
    dump_path = dewiki_source.ensure_dump()
    for index, article in enumerate(dewiki_source.iter_articles(dump_path)):
        if index >= DEWIKI_SKIP_ARTICLES:
            yield article


def build_encyclopedia() -> list[SentenceRow]:
    rows: list[SentenceRow] = []
    seen: set[str] = set()
    for article in _dewiki_articles():
        document = dewiki_source.clean_wikitext(article.wikitext)
        texts = _fresh_texts(document, seen)
        seen.update(texts)
        rows.extend(
            SentenceRow(
                genre="encyclopedia", lang="de", source="dewiki-20180920", document=article.page_id, text=text
            )
            for text in texts
        )
        if len(rows) >= GENRE_TARGETS["encyclopedia"]:
            break
    return rows[: GENRE_TARGETS["encyclopedia"]]


GENRE_BUILDERS = {"encyclopedia": build_encyclopedia, "literature": build_literature}


def build_corpus() -> dict[str, list[SentenceRow]]:
    return {genre: builder() for genre, builder in GENRE_BUILDERS.items()}


def serialize_corpus(corpus: Mapping[str, Sequence[SentenceRow]]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lines = (encoder.encode(row) for genre in GENRE_BUILDERS for row in corpus[genre])
    return "".join(line + "\n" for line in lines)


def _genre_manifest(genre: str, rows: Sequence[SentenceRow]) -> dict[str, str | int]:
    return {
        "sentences": len(rows),
        "documents": len({row["document"] for row in rows}),
        "target": GENRE_TARGETS[genre],
        "note": GENRE_NOTES[genre],
    }


def build_manifest(corpus: Mapping[str, Sequence[SentenceRow]], digest: str) -> dict[str, object]:
    return {
        "corpus": OUTPUT_PATH.name,
        "sha256": digest,
        "lang": "de",
        "sentences_per_document": SENTENCES_PER_DOCUMENT,
        "dewiki_skip_articles": DEWIKI_SKIP_ARTICLES,
        "coverage_gap": COVERAGE_GAP,
        "genres": {genre: _genre_manifest(genre, rows) for genre, rows in corpus.items()},
    }


def main() -> None:
    corpus = build_corpus()
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
