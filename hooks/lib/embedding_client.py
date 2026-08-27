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
except ImportError:
    from embedding_lease import acquire, may_unload
    from embedding_lease import release as release_lease

DEFAULT_URL = "http://127.0.0.1:8000/v1/embeddings"
# WHY: The x86 box serves the GGUF build of the same model behind a router that binds loopback, so it is reachable only through a forwarded port.
FALLBACK_URLS = ("http://127.0.0.1:8100/embed/v1/embeddings",)
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
    """Ordered because the first reachable host wins, and a machine that serves neither must cost one refused connection, not a hang."""
    listed = os.environ.get("ADW_EMBEDDING_URLS", "").strip()
    if listed:
        return tuple(part.strip() for part in listed.split(",") if part.strip())
    single = os.environ.get("ADW_EMBEDDING_URL", "").strip()
    if single:
        return (single,)
    return (DEFAULT_URL, *FALLBACK_URLS)


def model_name() -> str:
    return _text_setting("ADW_EMBEDDING_MODEL", DEFAULT_MODEL)


def unload_url() -> str:
    """Empty by default because assuming an unload route a server may not serve would turn a working setup into a 404 every turn."""
    return os.environ.get("ADW_EMBEDDING_UNLOAD_URL", "").strip()


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
    """Only the last live holder posts the unload, because another session mid turn would lose the model underneath it."""
    if not may_unload(session_id, now, root):
        return False
    url = unload_url()
    if not url:
        return False
    return _request(url, {"model": model_name()}, REQUEST_TIMEOUT_SECONDS) is not None
