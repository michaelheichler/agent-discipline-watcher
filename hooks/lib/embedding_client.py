"""Kept out of the blocking hook path because a gate that waits on a model server would stall every write."""
from __future__ import annotations

import ipaddress
import json
import math
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

try:
    from .embedding_lease import acquire, register_root
    from .embedding_lease import release as release_lease
    from .embedding_server import LOCK_NAME, default_root, is_loopback_host, parse_endpoint, running_url
    from .model_store import exclusive
except ImportError:
    from embedding_lease import acquire, register_root
    from embedding_lease import release as release_lease
    from embedding_server import LOCK_NAME, default_root, is_loopback_host, parse_endpoint, running_url
    from model_store import exclusive

DEFAULT_MODEL = "LFM2.5-Embedding-350M"
REQUEST_TIMEOUT_SECONDS = 30.0
RETRY_DELAYS_SECONDS = (0.5, 2.0)
MAX_BATCH = 32
MAX_INPUTS = 8192
MAX_TEXT_CHARS = 16_384
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 4 * 1_048_576
MAX_RESPONSE_ROWS = MAX_INPUTS
MAX_VECTOR_DIMENSIONS = 4096
LOCAL_ONLY_ENV = "ADW_EMBEDDING_LOCAL_ONLY"
APPROVED_HOSTS_ENV = "ADW_EMBEDDING_APPROVED_HOSTS"
APPROVED_PROVIDERS_ENV = "ADW_EMBEDDING_APPROVED_PROVIDERS"
PROBE_TEXT = "probe"
# WHY: One short attempt per host, because the probe runs inside a prompt hook and a retry ladder there would stall the turn.
PROBE_TIMEOUT_SECONDS = 3.0
Vector = tuple[float, ...]


def _text_setting(env_name: str, default: str) -> str:
    return os.environ.get(env_name, "").strip() or default


def _local_only() -> bool:
    """Keep remote embedding egress disabled unless the operator opts out explicitly."""
    value = os.environ.get(LOCAL_ONLY_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _approved_hosts() -> frozenset[str]:
    """Read exact remote provider hosts from explicit approval settings."""
    listed = ",".join(
        (
            os.environ.get(APPROVED_HOSTS_ENV, ""),
            os.environ.get(APPROVED_PROVIDERS_ENV, ""),
        )
    )
    return frozenset(part.strip().rstrip(".").lower() for part in listed.split(",") if part.strip())


def _approved_url(url: object) -> bool:
    """Allow loopback endpoints or HTTPS hosts explicitly approved for remote egress."""
    parsed = parse_endpoint(url)
    if parsed is None:
        return False
    hostname = parsed.hostname
    if is_loopback_host(hostname):
        return True
    if _local_only() or parsed.scheme != "https":
        return False
    try:
        if ipaddress.ip_address(hostname).is_private:
            return False
    except ValueError:
        pass
    return hostname.rstrip(".").lower() in _approved_hosts()

def _allows_remote(config: dict | None) -> bool:
    """Require an explicit project boundary and operator approval before remote source egress."""
    if config is None:
        return False
    boundary = config.get("data_boundary")
    return isinstance(boundary, dict) and type(boundary.get("enabled")) is bool and boundary["enabled"]  # pylint: disable=unidiomatic-typecheck


def embeddings_urls(config: dict | None = None) -> tuple[str, ...]:
    """Return only local or explicitly approved embedding endpoints in configured order."""
    listed = os.environ.get("ADW_EMBEDDING_URLS", "").strip()
    if listed:
        candidates = tuple(part.strip() for part in listed.split(",") if part.strip())
    else:
        single = os.environ.get("ADW_EMBEDDING_URL", "").strip()
        if single:
            candidates = (single,)
        else:
            supervised = running_url(default_root())
            candidates = (supervised,) if supervised else ()
    approved: list[str] = []
    for url in candidates:
        if not _approved_url(url):
            continue
        hostname = urlsplit(url).hostname
        if not is_loopback_host(hostname) and not _allows_remote(config):
            continue
        approved.append(url)
    return tuple(approved)


def model_name() -> str:
    return _text_setting("ADW_EMBEDDING_MODEL", DEFAULT_MODEL)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent an approved endpoint from forwarding source text elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirectHandler()
)


def _response_bytes(response) -> bytes:
    """Read a response only when both its advertised and actual sizes fit the cap."""
    header = response.headers.get("Content-Length")
    if header is not None:
        header = header.strip()
        if not header.isascii() or not header.isdigit():
            raise ValueError("embedding response Content-Length is invalid")
        try:
            length = int(header)
        except ValueError as error:
            raise ValueError("embedding response Content-Length is invalid") from error
        if length > MAX_RESPONSE_BYTES:
            raise ValueError("embedding response exceeds the size limit")
    else:
        length = None
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("embedding response exceeds the size limit")
    if length is not None and len(raw) != length:
        raise ValueError("embedding response is truncated")
    return raw


def _request_texts(texts: tuple[str, ...]) -> None:
    """Reject oversized client input before serializing or contacting an endpoint."""
    if len(texts) > MAX_INPUTS:
        raise ValueError(f"input contains more than {MAX_INPUTS} texts")
    if any(not isinstance(text, str) for text in texts):
        raise ValueError("input must contain only strings")
    if any(len(text) > MAX_TEXT_CHARS for text in texts):
        raise ValueError(f"input text exceeds {MAX_TEXT_CHARS} characters")


def _post(url: str, payload: dict, timeout: float) -> dict:
    """POST JSON to an approved endpoint and parse a bounded JSON response."""
    if not _approved_url(url):
        raise ValueError("embedding URL is not approved for source egress")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("embedding request exceeds the size limit")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
        raw = _response_bytes(response)
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ValueError("embedding response must be valid UTF-8 JSON") from error
    if not isinstance(body, dict):
        raise ValueError("embedding response must be a JSON object")
    return body


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


def _request(url: str, payload: dict, timeout: float, retry_delays: tuple[float, ...]) -> dict | None:
    for delay in retry_delays:
        body = _request_once(url, payload, timeout)
        if body is not None:
            return body
        time.sleep(delay)
    return _request_once(url, payload, timeout)


def _first_answering(urls: tuple[str, ...], payload: dict, timeout: float, retry_delays: tuple[float, ...]) -> dict | None:
    for url in urls:
        body = _request(url, payload, timeout, retry_delays)
        if body is not None:
            return body
    return None


def _vector(row: object) -> Vector:
    """Convert one finite, dimension-bounded embedding row without accepting malformed values."""
    if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
        raise ValueError("embedding response row is not an embedding object")
    values = row["embedding"]
    if not values or len(values) > MAX_VECTOR_DIMENSIONS:
        raise ValueError("embedding response vector has an invalid dimension")
    result: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("embedding response vector contains a non-number")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("embedding response vector contains a non-number") from error
        if not math.isfinite(number):
            raise ValueError("embedding response vector contains a non-finite number")
        result.append(number)
    return tuple(result)


def _vectors(body: dict) -> tuple[Vector, ...]:
    """Parse only a bounded OpenAI-style embedding data list."""
    if not isinstance(body, dict):
        raise ValueError("embedding response must be a JSON object")
    rows = body.get("data")
    if not isinstance(rows, list):
        raise ValueError("embedding response carries no data list")
    if len(rows) > MAX_RESPONSE_ROWS:
        raise ValueError("embedding response carries too many vectors")
    return tuple(_vector(row) for row in rows)


def embed(texts: tuple[str, ...], config: dict | None = None, *, retry_delays: tuple[float, ...] = RETRY_DELAYS_SECONDS) -> tuple[Vector, ...] | None:
    """Embed bounded input chunks while preserving ordered endpoint failover."""
    if not texts:
        return ()
    _request_texts(texts)
    urls = embeddings_urls(config)
    if not urls:
        return None
    vectors: list[Vector] = []
    for start in range(0, len(texts), MAX_BATCH):
        batch = texts[start : start + MAX_BATCH]
        body = _first_answering(
            urls,
            {"model": model_name(), "input": list(batch)},
            REQUEST_TIMEOUT_SECONDS,
            retry_delays,
        )
        if body is None:
            return None
        answered = _vectors(body)
        if len(answered) != len(batch):
            raise ValueError(
                f"embedding server returned {len(answered)} vectors for {len(batch)} inputs"
            )
        vectors.extend(answered)
    return tuple(vectors)


def probe() -> str | None:
    """Names the host that answered, because the caller records which of the two carried the session."""
    payload = {"model": model_name(), "input": [PROBE_TEXT]}
    for url in embeddings_urls():
        if _request_once(url, payload, PROBE_TIMEOUT_SECONDS) is not None:
            return url
    return None


def ensure_loaded(session_id: str, now: float, root: str | os.PathLike[str] | None, owner_pid: int) -> str | None:
    """Retain demand through cold startup, and serialize acquisition with the last holder's unload."""
    server_root = default_root()
    with exclusive(server_root / LOCK_NAME):
        register_root(server_root, root)
        acquire(session_id, now, root, owner_pid)
    return probe()


def release(session_id: str, root: str | os.PathLike[str] | None) -> bool:
    """Lease only, since a worker kill outlasts the 10 s Stop hook."""
    server_root = default_root()
    with exclusive(server_root / LOCK_NAME):
        register_root(server_root, root)
        return release_lease(session_id, root)
