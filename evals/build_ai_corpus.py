#!/usr/bin/env python3
"""Draws real assistant replies because the rules that name an AI tell fired zero times on 60000 sentences of human prose."""
import hashlib
import json
import os
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
from build_human_corpus import SENTENCES_PER_DOCUMENT, _sentences, _spread


class Source(NamedTuple):
    name: str
    dataset: str
    conversations: tuple[tuple[str, str], ...]
    sentences: int


class ReplyRow(NamedTuple):
    source: str
    model: str
    row: int
    text: str


OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "corpus_ai_sentences.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_ai_manifest.json"
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
CACHE_ROOT = Path.home() / ".adw" / "cache" / "datasets"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60
REQUEST_PAUSE = 1.0
# WHY: The rows service answers 429 on a long sweep, so the ladder is minutes rather than seconds.
RETRY_DELAYS = (5.0, 15.0, 45.0, 120.0)
ENGLISH = "English"
ASSISTANT = "assistant"
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
SOURCES = (
    Source("wildchat", "allenai/WildChat-4.8M", (("conversation", "model"),), 60000),
    Source(
        "arena",
        "lmarena-ai/arena-human-preference-100k",
        (("conversation_a", "model_a"), ("conversation_b", "model_b")),
        30000,
    ),
)
COVERAGE_NOTE = "Chat replies to public prompts, so the register is conversational and carries no repository or code review prose."


def _page_url(dataset: str, offset: int) -> str:
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": "default", "split": "train", "offset": offset, "length": PAGE_SIZE}
    )
    return f"{ROWS_ENDPOINT}?{query}"


def _token() -> str:
    """Sent when present because the anonymous cap on the rows service stops a sweep this long partway through."""
    from_environment = os.environ.get("HF_TOKEN", "").strip()
    if from_environment:
        return from_environment
    path = Path.home() / ".cache" / "huggingface" / "token"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _read_page(url: str) -> dict:
    request = urllib.request.Request(url)
    token = _token()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _attempt_page(url: str, delay: float) -> dict | None:
    try:
        return _read_page(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        time.sleep(delay)
        return None


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
    """Cached because a rate limit mid sweep would otherwise throw away every page already paid for."""
    path = _cache_path(dataset, offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page), encoding="utf-8")


def _fetch(dataset: str, offset: int) -> dict:
    """Retries because the rows service rate limits a long sweep, and raises the last error rather than shortening the corpus in silence."""
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


def _replies(row: dict, field: str) -> list[str]:
    turns = row.get(field)
    if not isinstance(turns, list):
        return []
    return [
        CODE_FENCE_RE.sub(" ", turn["content"])
        for turn in turns
        if isinstance(turn, dict) and turn.get("role") == ASSISTANT and isinstance(turn.get("content"), str)
    ]


def _row_sentences(row: dict, source: Source, number: int) -> list[ReplyRow]:
    if row.get("language") != ENGLISH:
        return []
    rows: list[ReplyRow] = []
    for field, model_field in source.conversations:
        model = str(row.get(model_field, "unknown"))
        texts = [text for reply in _replies(row, field) for text in _sentences(reply)]
        rows.extend(
            ReplyRow(source.name, model, number, text)
            for text in _spread(texts, SENTENCES_PER_DOCUMENT)
        )
    return rows


def _total_rows(dataset: str) -> int:
    return int(_fetch(dataset, 0)["num_rows_total"])


def _offsets(total: int, wanted_pages: int) -> list[int]:
    """Strides across the whole set rather than reading the head, because the earliest rows are all one model from 2023."""
    stride = max(PAGE_SIZE, total // max(wanted_pages, 1))
    return [index * stride for index in range(wanted_pages) if index * stride < total]


def build_source(source: Source) -> list[ReplyRow]:
    total = _total_rows(source.dataset)
    pages = max(1, source.sentences // (PAGE_SIZE * 2))
    rows: list[ReplyRow] = []
    seen: set[str] = set()
    for offset in _offsets(total, pages):
        for index, entry in enumerate(_fetch(source.dataset, offset)["rows"]):
            fresh = [row for row in _row_sentences(entry["row"], source, offset + index) if row.text not in seen]
            seen.update(row.text for row in fresh)
            rows.extend(fresh)
        print(f"  {source.name}: {len(rows)} sentences at offset {offset}", flush=True)
        if len(rows) >= source.sentences:
            break
        time.sleep(REQUEST_PAUSE)
    return rows[: source.sentences]


def serialize(rows: list[ReplyRow]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row._asdict()) + "\n" for row in rows)


def _source_manifest(source: Source, rows: list[ReplyRow]) -> dict[str, object]:
    models = Counter(row.model for row in rows if row.source == source.name)
    return {
        "dataset": source.dataset,
        "sentences": sum(row.source == source.name for row in rows),
        "models": dict(models.most_common(12)),
        "distinct_models": len(models),
    }


def build_manifest(rows: list[ReplyRow], digest: str) -> dict[str, object]:
    return {
        "corpus": OUTPUT_PATH.name,
        "sha256": digest,
        "coverage_note": COVERAGE_NOTE,
        "sentences_per_document": SENTENCES_PER_DOCUMENT,
        "sources": {source.name: _source_manifest(source, rows) for source in SOURCES},
    }


def main() -> None:
    rows: list[ReplyRow] = []
    for source in SOURCES:
        rows.extend(build_source(source))
    serialized = serialize(rows)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(rows, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    for source in SOURCES:
        print(f"{source.name}: {sum(row.source == source.name for row in rows)} sentences")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
