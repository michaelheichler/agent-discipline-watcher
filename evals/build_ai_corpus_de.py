#!/usr/bin/env python3
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from build_human_corpus_de import CACHE_ROOT, PAGE_SIZE, REQUEST_PAUSE, REQUEST_TIMEOUT, RETRY_DELAYS, SENTENCES_PER_DOCUMENT, _sentences, _spread


class ReplyRow(NamedTuple):
    lang: str
    source: str
    model: str
    row: int
    text: str


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "corpus_ai_sentences_de.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_ai_manifest_de.json"
FILTER_ENDPOINT = "https://datasets-server.huggingface.co/filter"
ASSISTANT = "assistant"
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
WILDCHAT_DATASET = "allenai/WildChat-4.8M"
WILDCHAT_WHERE = "\"language\"='German'"
WILDCHAT_TARGET = 6000
COLING_DATASET = "Jinyan1/COLING_2025_MGT_multingual"
COLING_WHERE = "\"lang\"='de' AND \"label\"=1"
COLING_SPLITS = ("train", "dev")
COLING_TARGET = 15000
COVERAGE_NOTE = "COLING rows are all News/Wikipedia GPT-3.5 output, so no chat genre overlaps WildChat here."


def _filter_url(dataset: str, split: str, where: str, offset: int) -> str:
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": "default", "split": split, "where": where, "offset": offset, "length": PAGE_SIZE}
    )
    return f"{FILTER_ENDPOINT}?{query}"


def _read_page(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _cache_path(dataset: str, split: str, offset: int) -> Path:
    return CACHE_ROOT / dataset.replace("/", "--") / f"filter-{split}-{offset}.json"


def _cached(dataset: str, split: str, offset: int) -> dict | None:
    path = _cache_path(dataset, split, offset)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _store(dataset: str, split: str, offset: int, page: dict) -> None:
    path = _cache_path(dataset, split, offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page), encoding="utf-8")


def _attempt_page(url: str, delay: float) -> dict | None:
    try:
        return _read_page(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        time.sleep(delay)
        return None


def _fetch_filtered(dataset: str, split: str, where: str, offset: int) -> dict:
    page = _cached(dataset, split, offset)
    if page is not None:
        return page
    url = _filter_url(dataset, split, where, offset)
    for delay in RETRY_DELAYS:
        page = _attempt_page(url, delay)
        if page is not None:
            _store(dataset, split, offset, page)
            return page
    page = _read_page(url)
    _store(dataset, split, offset, page)
    return page


def _filtered_rows(dataset: str, split: str, where: str) -> list[tuple[int, dict]]:
    first = _fetch_filtered(dataset, split, where, 0)
    total = int(first["num_rows_total"])
    found = [(entry["row_idx"], entry["row"]) for entry in first["rows"]]
    offset = PAGE_SIZE
    while offset < total:
        page = _fetch_filtered(dataset, split, where, offset)
        found.extend((entry["row_idx"], entry["row"]) for entry in page["rows"])
        offset += PAGE_SIZE
        time.sleep(REQUEST_PAUSE)
    return found


def _wildchat_replies(row: dict) -> list[str]:
    turns = row.get("conversation")
    if not isinstance(turns, list):
        return []
    return [
        CODE_FENCE_RE.sub(" ", turn["content"])
        for turn in turns
        if isinstance(turn, dict) and turn.get("role") == ASSISTANT and isinstance(turn.get("content"), str)
    ]


def build_wildchat() -> list[ReplyRow]:
    rows: list[ReplyRow] = []
    seen: set[str] = set()
    for number, row in _filtered_rows(WILDCHAT_DATASET, "train", WILDCHAT_WHERE):
        model = str(row.get("model", "unknown"))
        texts = [text for reply in _wildchat_replies(row) for text in _sentences(reply)]
        fresh = [text for text in _spread(texts, SENTENCES_PER_DOCUMENT) if text not in seen]
        seen.update(fresh)
        rows.extend(ReplyRow("de", "wildchat", model, number, text) for text in fresh)
        if len(rows) >= WILDCHAT_TARGET:
            break
    return rows[:WILDCHAT_TARGET]


def _coling_documents() -> list[tuple[int, dict]]:
    found = []
    for split in COLING_SPLITS:
        found.extend(_filtered_rows(COLING_DATASET, split, COLING_WHERE))
    return found


def build_coling() -> list[ReplyRow]:
    rows: list[ReplyRow] = []
    seen: set[str] = set()
    for number, row in _coling_documents():
        model = str(row.get("model", "unknown"))
        texts = _sentences(str(row.get("text", "")))
        fresh = [text for text in _spread(texts, SENTENCES_PER_DOCUMENT) if text not in seen]
        seen.update(fresh)
        rows.extend(ReplyRow("de", "coling", model, number, text) for text in fresh)
        if len(rows) >= COLING_TARGET:
            break
    return rows[:COLING_TARGET]


SOURCE_BUILDERS = {"wildchat": build_wildchat, "coling": build_coling}


def serialize(rows: list[ReplyRow]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row._asdict()) + "\n" for row in rows)


def _source_manifest(source: str, rows: list[ReplyRow]) -> dict[str, object]:
    mine = [row for row in rows if row.source == source]
    models = Counter(row.model for row in mine)
    return {"sentences": len(mine), "models": dict(models.most_common(12)), "distinct_models": len(models)}


def build_manifest(rows: list[ReplyRow], digest: str) -> dict[str, object]:
    return {
        "corpus": OUTPUT_PATH.name,
        "sha256": digest,
        "lang": "de",
        "coverage_note": COVERAGE_NOTE,
        "sentences_per_document": SENTENCES_PER_DOCUMENT,
        "sources": {
            "wildchat": dict(_source_manifest("wildchat", rows), dataset=WILDCHAT_DATASET),
            "coling": dict(_source_manifest("coling", rows), dataset=COLING_DATASET),
        },
    }


def main() -> None:
    rows: list[ReplyRow] = []
    for name, builder in SOURCE_BUILDERS.items():
        built = builder()
        rows.extend(built)
        print(f"{name}: {len(built)} sentences")
    serialized = serialize(rows)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(rows, digest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
