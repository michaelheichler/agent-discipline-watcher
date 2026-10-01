#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Iterator

from build_human_corpus_de import CACHE_ROOT
from dewiki_source import _download

COLING_DATASET = "Jinyan1/COLING_2025_MGT_multingual"
COLING_REVISION = "da603651a8929a3790937c2c2b01bde23662111f"
COLING_SPLIT_FILES: dict[str, tuple[str, ...]] = {
    "train": (
        "data/train-00000-of-00003.parquet",
        "data/train-00001-of-00003.parquet",
        "data/train-00002-of-00003.parquet",
    ),
    "dev": ("data/dev-00000-of-00001.parquet",),
}
COLING_LANG = "de"
COLING_LABEL = 1
COLING_COLUMNS = ("model", "text")

WILDCHAT_DATASET = "allenai/WildChat-4.8M"
WILDCHAT_REVISION = "c827c6df8fcf008219ffaffa4d1dd77491099367"
WILDCHAT_FILE_COUNT = 86
WILDCHAT_FILES: tuple[str, ...] = tuple(
    f"data/train-{index:05d}-of-{WILDCHAT_FILE_COUNT:05d}.parquet" for index in range(WILDCHAT_FILE_COUNT)
)
WILDCHAT_LANGUAGE = "German"
WILDCHAT_TURN_PROJECTION = "list_transform(conversation, x -> struct_pack(role := x.role, content := x.content))"


def _connection():
    import duckdb  # pylint: disable=import-error

    connection = duckdb.connect()
    connection.execute("INSTALL httpfs")
    connection.execute("LOAD httpfs")
    return connection


def _resolve_url(dataset: str, revision: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"


def _row_count(connection, parquet_source: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM read_parquet('{parquet_source}')").fetchone()[0]


def _scan_query(parquet_source: str, select: str, where: str) -> str:
    return (
        f"SELECT file_row_number, {select} "
        f"FROM read_parquet('{parquet_source}', file_row_number = true) "
        f"WHERE {where} ORDER BY file_row_number"
    )


def _struct_rows(connection, query: str) -> list[dict]:
    result = connection.execute(query)
    names = [description[0] for description in result.description]
    return [dict(zip(names, record)) for record in result.fetchall()]


def _coling_cache_path(path: str) -> Path:
    return CACHE_ROOT / COLING_DATASET.replace("/", "--") / "raw" / path.replace("/", "--")


def ensure_coling_file(path: str) -> Path:
    destination = _coling_cache_path(path)
    if not destination.is_file():
        _download(destination, _resolve_url(COLING_DATASET, COLING_REVISION, path))
    return destination


def coling_rows(split: str) -> list[tuple[int, dict]]:
    connection = _connection()
    where = f"lang = '{COLING_LANG}' AND label = {COLING_LABEL}"
    found: list[tuple[int, dict]] = []
    offset = 0
    for path in COLING_SPLIT_FILES[split]:
        local_path = ensure_coling_file(path).as_posix()
        total = _row_count(connection, local_path)
        query = _scan_query(local_path, ", ".join(COLING_COLUMNS), where)
        for row in _struct_rows(connection, query):
            found.append((offset + row.pop("file_row_number"), row))
        offset += total
    return found


def _wildchat_cache_path(path: str) -> Path:
    return CACHE_ROOT / WILDCHAT_DATASET.replace("/", "--") / "german" / (path.replace("/", "--") + ".jsonl")


def _write_wildchat_cache(cache_path: Path, total_rows: int, rows: list[dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    header = encoder.encode({"revision": WILDCHAT_REVISION, "total_rows": total_rows})
    body = (encoder.encode(row) for row in rows)
    cache_path.write_text("".join(line + "\n" for line in (header, *body)), encoding="utf-8")


def _read_wildchat_cache(cache_path: Path) -> tuple[int, list[dict]]:
    text = cache_path.read_text(encoding="utf-8")
    lines = text.split("\n")[:-1]
    header = json.loads(lines[0])
    return header["total_rows"], [json.loads(line) for line in lines[1:]]


def _wildchat_file_rows(connection, path: str) -> tuple[int, list[dict]]:
    cache_path = _wildchat_cache_path(path)
    if cache_path.is_file():
        return _read_wildchat_cache(cache_path)
    url = _resolve_url(WILDCHAT_DATASET, WILDCHAT_REVISION, path)
    total = _row_count(connection, url)
    select = f"model, {WILDCHAT_TURN_PROJECTION} AS conversation"
    query = _scan_query(url, select, f"language = '{WILDCHAT_LANGUAGE}'")
    rows = _struct_rows(connection, query)
    _write_wildchat_cache(cache_path, total, rows)
    return total, rows


def wildchat_rows() -> Iterator[tuple[int, dict]]:
    connection = _connection()
    offset = 0
    for path in WILDCHAT_FILES:
        total, rows = _wildchat_file_rows(connection, path)
        for row in rows:
            yield offset + row.pop("file_row_number"), row
        offset += total
