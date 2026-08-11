"""Every failure here must return None because callers need deterministic behavior with no dependency on an external process."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess

PROTOCOL_VERSION = 1
PROTOTYPE_VERSION = 1

DEFAULT_TIMEOUT_SECONDS = 5
MAX_CANDIDATES = 20
MAX_PROTOTYPES = 40
MAX_TEXT_CHARS = 400
MAX_INPUT_BYTES = 200_000
MAX_OUTPUT_BYTES = 1_000_000

ENV_VAR = "ADW_EMBEDDING_HELPER"

_cache: dict[tuple[str, int, str], list[float]] = {}


def clear_cache() -> None:
    _cache.clear()


def helper_path() -> str | None:
    """Read only the env var, never project config, because a repo must not be able to choose a command to run."""
    value = os.environ.get(ENV_VAR)
    if not value or not os.path.isabs(value):
        return None
    if not os.path.isfile(value) or not os.access(value, os.X_OK):
        return None
    return value


def _helper_identity(path: str) -> str | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return f"{path}:{stat.st_mtime_ns}:{stat.st_size}"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _clean_vector(vector: object, dim: int | None) -> list[float] | None:
    if not isinstance(vector, list) or not vector:
        return None
    if dim is not None and len(vector) != dim:
        return None
    clean: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        clean.append(number)
    return clean


def _parse_matrix(raw: bytes, expected: int) -> list[list[float]] | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    vectors = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(vectors, list) or len(vectors) != expected:
        return None
    result: list[list[float]] = []
    dim = len(vectors[0]) if vectors and isinstance(vectors[0], list) else None
    for vector in vectors:
        clean = _clean_vector(vector, dim)
        if clean is None:
            return None
        result.append(clean)
    return result


def _invoke_helper(path: str, texts: list[str], timeout: float) -> list[list[float]] | None:
    payload = json.dumps({"protocol_version": PROTOCOL_VERSION, "texts": texts}).encode("utf-8")
    if len(payload) > MAX_INPUT_BYTES:
        return None
    try:
        process = subprocess.Popen(
            [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False,
        )
    except OSError:
        return None
    try:
        stdout, _ = process.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill and wait so the child never outlives this call, because the model unload relies on process exit.
        process.kill()
        process.wait()
        return None
    if process.returncode != 0:
        return None
    if len(stdout) > MAX_OUTPUT_BYTES:
        return None
    return _parse_matrix(stdout, len(texts))


def _lookup_or_queue(
    kind: str, ident: object, text: str, identity: str,
    vectors: dict[tuple[str, object], list[float]],
    fetch_keys: list[tuple[str, object, tuple[str, int, str]]],
    fetch_texts: list[str],
) -> None:  # ponytail: keeps enrich() under the line cap; group into a batch object if signature grows again
    key = (identity, PROTOTYPE_VERSION, _text_hash(text[:MAX_TEXT_CHARS]))
    if key in _cache:
        vectors[(kind, ident)] = _cache[key]
    else:
        fetch_keys.append((kind, ident, key))
        fetch_texts.append(text[:MAX_TEXT_CHARS])


def _resolve_vectors(
    candidates: list[dict], prototypes: list[dict], identity: str, path: str, timeout: float
) -> dict[tuple[str, object], list[float]] | None:
    fetch_texts: list[str] = []
    fetch_keys: list[tuple[str, object, tuple[str, int, str]]] = []
    vectors: dict[tuple[str, object], list[float]] = {}
    for candidate in candidates:
        _lookup_or_queue("c", candidate.get("id"), str(candidate.get("text", "")), identity, vectors, fetch_keys, fetch_texts)
    for index, prototype in enumerate(prototypes):
        _lookup_or_queue("p", index, str(prototype.get("text", "")), identity, vectors, fetch_keys, fetch_texts)
    if not fetch_texts:
        return vectors
    fetched = _invoke_helper(path, fetch_texts, timeout)
    if fetched is None:
        return None
    for (kind, ident, key), vector in zip(fetch_keys, fetched):
        vectors[(kind, ident)] = vector
        _cache[key] = vector
    return vectors


def enrich(
    candidates: list[dict],
    prototypes: list[dict],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, dict] | None:
    """Return nearest-prototype matches per candidate id, or None on any failure or absence."""
    path = helper_path()
    if path is None or not candidates or not prototypes:
        return None
    identity = _helper_identity(path)
    if identity is None:
        return None
    candidates = candidates[:MAX_CANDIDATES]
    prototypes = prototypes[:MAX_PROTOTYPES]
    vectors = _resolve_vectors(candidates, prototypes, identity, path, timeout)
    if vectors is None:
        return None
    return _nearest_matches(candidates, prototypes, vectors)


def _score_prototypes(
    candidate_vector: list[float], prototypes: list[dict], vectors: dict[tuple[str, object], list[float]]
) -> list[tuple[float, dict]]:
    scored = []
    for index, prototype in enumerate(prototypes):
        prototype_vector = vectors.get(("p", index))
        if prototype_vector is not None:
            scored.append((_cosine(candidate_vector, prototype_vector), prototype))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _nearest_matches(
    candidates: list[dict], prototypes: list[dict], vectors: dict[tuple[str, object], list[float]]
) -> dict[str, dict] | None:
    matches: dict[str, dict] = {}
    for candidate in candidates:
        candidate_id = candidate.get("id")
        candidate_vector = vectors.get(("c", candidate_id))
        if candidate_vector is None:
            continue
        scored = _score_prototypes(candidate_vector, prototypes, vectors)
        if not scored:
            continue
        best_similarity, best_prototype = scored[0]
        margin = best_similarity - scored[1][0] if len(scored) > 1 else best_similarity
        matches[str(candidate_id)] = {
            "label": str(best_prototype.get("label", "")),
            "example": str(best_prototype.get("text", ""))[:MAX_TEXT_CHARS],
            "similarity": round(best_similarity, 4),
            "margin": round(margin, 4),
        }
    return matches or None
