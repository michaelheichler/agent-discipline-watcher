"""Kept out of the blocking hook path because a gate that waits on a model server would stall every write."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

try:
    from .embedding_lease import acquire, may_unload
    from .embedding_lease import release as release_lease
    from .embedding_server import default_root, running_url, stop
except ImportError:
    from embedding_lease import acquire, may_unload
    from embedding_lease import release as release_lease
    from embedding_server import default_root, running_url, stop

DEFAULT_MODEL = "LFM2.5-Embedding-350M"
REQUEST_TIMEOUT_SECONDS = 30.0
RETRY_DELAYS_SECONDS = (0.5, 2.0)
PROBE_TEXT = "probe"
# WHY: One short attempt per host, because the probe runs inside a prompt hook and a retry ladder there would stall the turn.
PROBE_TIMEOUT_SECONDS = 3.0
Vector = tuple[float, ...]


def _text_setting(env_name: str, default: str) -> str:
    return os.environ.get(env_name, "").strip() or default


def embeddings_urls() -> tuple[str, ...]:
    """Falls back to the supervised server rather than a fixed address, because a pinned host is one developer's machine and not a release."""
    listed = os.environ.get("ADW_EMBEDDING_URLS", "").strip()
    if listed:
        return tuple(part.strip() for part in listed.split(",") if part.strip())
    single = os.environ.get("ADW_EMBEDDING_URL", "").strip()
    if single:
        return (single,)
    supervised = running_url(default_root())
    return (supervised,) if supervised else ()


def model_name() -> str:
    return _text_setting("ADW_EMBEDDING_MODEL", DEFAULT_MODEL)


def _post(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_once(url: str, payload: dict, timeout: float) -> dict | None:
    """A 4xx raises because a wrong model or route is a configuration defect the operator must see, not an absent server."""
    try:
        return _post(url, payload, timeout)
    except urllib.error.HTTPError as error:
        if error.code < 500:
            raise
        return None
    except OSError:
        return None


def _request(url: str, payload: dict, timeout: float) -> dict | None:
    for delay in RETRY_DELAYS_SECONDS:
        body = _request_once(url, payload, timeout)
        if body is not None:
            return body
        time.sleep(delay)
    return _request_once(url, payload, timeout)


def _first_answering(urls: tuple[str, ...], payload: dict, timeout: float) -> dict | None:
    for url in urls:
        body = _request(url, payload, timeout)
        if body is not None:
            return body
    return None


def _vector(row: object) -> Vector:
    if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
        raise ValueError(f"embedding response row is not an embedding object: {row!r}")
    return tuple(float(value) for value in row["embedding"])


def _vectors(body: dict) -> tuple[Vector, ...]:
    rows = body.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"embedding response carries no data list: {body!r}")
    return tuple(_vector(row) for row in rows)


def embed(texts: tuple[str, ...]) -> tuple[Vector, ...] | None:
    if not texts:
        return ()
    body = _first_answering(
        embeddings_urls(),
        {"model": model_name(), "input": list(texts)},
        REQUEST_TIMEOUT_SECONDS,
    )
    if body is None:
        return None
    vectors = _vectors(body)
    if len(vectors) != len(texts):
        raise ValueError(
            f"embedding server returned {len(vectors)} vectors for {len(texts)} inputs"
        )
    return vectors


def probe() -> str | None:
    """Names the host that answered, because the caller records which of the two carried the session."""
    payload = {"model": model_name(), "input": [PROBE_TEXT]}
    for url in embeddings_urls():
        if _request_once(url, payload, PROBE_TIMEOUT_SECONDS) is not None:
            return url
    return None


def ensure_loaded(
    session_id: str, now: float, root: str | os.PathLike[str] | None, owner_pid: int
) -> str | None:
    """Takes the lease before the probe, because a session that unloads between the probe and the first real call would strand the caller."""
    acquire(session_id, now, root, owner_pid)
    answered = probe()
    if answered is None:
        release_lease(session_id, root)
    return answered


def release(session_id: str, now: float, root: str | os.PathLike[str] | None) -> bool:
    """Only the last live holder stops the server, because another session mid turn would lose the model underneath it."""
    if not may_unload(session_id, now, root):
        return False
    return stop(default_root())
