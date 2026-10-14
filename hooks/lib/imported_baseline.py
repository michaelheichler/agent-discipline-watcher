"""Content the agent did not write gets a session baseline, because git cannot vouch for copied or untracked files."""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

try:
    from . import session_state
except ImportError:
    import session_state

STATE_KEY = "imported_baseline"
STORE_DIRNAME = "imported"
MAX_SNAPSHOT_BYTES = 1_000_000
MAX_SNAPSHOTS = 1000
GIT_BASELINE = ""
NEW_FILE = "new"
_STATE_CACHE: dict[tuple[str, str], tuple[tuple[int, int], dict[str, str]]] = {}


@dataclass(frozen=True, slots=True)
class Snapshot:
    digest: str
    text: str | None


def path_key(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(os.path.expanduser(os.fspath(path)))


def _stream_digest(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1 << 16), b""):
        digest.update(block)
    return digest.hexdigest()


def file_digest(path: str | os.PathLike[str]) -> str | None:
    try:
        with open(path, "rb") as handle:
            return _stream_digest(handle)
    except OSError:
        return None


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _store(session_id: str, root: str | os.PathLike[str] | None) -> Path:
    return session_state.session_directory(session_id, root) / STORE_DIRNAME


def _entries(state: dict) -> dict[str, str]:
    stored = state.get(STATE_KEY)
    if not isinstance(stored, dict):
        return {}
    return {key: value for key, value in stored.items() if isinstance(key, str) and isinstance(value, str)}


def entries(session_id: str, root: str | os.PathLike[str] | None) -> dict[str, str]:
    """Cached on the state file stamp, because Stop asks once per tracked path."""
    if not session_id:
        return {}
    state_file = session_state.session_directory(session_id, root) / session_state.STATE_FILENAME
    try:
        stat = state_file.stat()
    except OSError:
        return {}
    cache_key = (session_id, str(state_file))
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _STATE_CACHE.get(cache_key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    found = _entries(session_state.read_state(session_id, root))
    _STATE_CACHE[cache_key] = (stamp, found)
    return found


def _write_blob(store: Path, digest: str, data: bytes) -> None:
    target = store / digest
    if target.exists():
        return
    store.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=store, prefix=".blob.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _captured(path: Path, store: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return file_digest(path)
        data = path.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256(data).hexdigest()
    _write_blob(store, digest, data)
    return digest


def _merged(stored: dict[str, str], marks: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    merged = dict(stored)
    changed = []
    for key, digest in marks.items():
        if merged.get(key) == digest:
            continue
        if key not in merged and len(merged) >= MAX_SNAPSHOTS:
            continue
        merged[key] = digest
        changed.append(key)
    return merged, changed


def _mark(session_id: str, marks: dict[str, str], root: str | os.PathLike[str] | None) -> list[str]:
    changed: list[str] = []

    def mutate(state: dict) -> dict:
        merged, keys = _merged(_entries(state), marks)
        changed.extend(keys)
        return {**state, STATE_KEY: merged} if keys else state

    if marks:
        session_state.update_state(session_id, mutate, root)
    return changed


def snapshot_many(session_id: str, paths: list[str], root: str | os.PathLike[str] | None) -> list[str]:
    """Return the keys whose baseline is new, so an identical re-import reports nothing twice."""
    if not session_id:
        return []
    store = _store(session_id, root)
    marks: dict[str, str] = {}
    for raw in paths:
        digest = _captured(Path(path_key(raw)), store)
        if digest is not None:
            marks[path_key(raw)] = digest
    return _mark(session_id, marks, root)


def _first_mark(path: Path, store: Path, has_git: Callable[[Path], bool]) -> str | None:
    if not path.is_file():
        return NEW_FILE
    if has_git(path):
        return GIT_BASELINE
    return _captured(path, store)


def note_first_seen(session_id: str, paths: list[str], root: str | os.PathLike[str] | None, has_git: Callable[[Path], bool]) -> None:
    """Taken before the first edit, because an untracked file has no other record of the text the agent found."""
    if not session_id:
        return
    seen = entries(session_id, root)
    store = _store(session_id, root)
    marks: dict[str, str] = {}
    for key in dict.fromkeys(path_key(raw) for raw in paths):
        mark = None if key in seen else _first_mark(Path(key), store, has_git)
        if mark is not None:
            marks[key] = mark
    _mark(session_id, marks, root)


def note_written(session_id: str, paths: list[str], root: str | os.PathLike[str] | None) -> None:
    """Claimed after a write nobody saw first, because a later first sight must not baseline the agent's own text."""
    if not session_id:
        return
    seen = entries(session_id, root)
    _mark(session_id, {key: NEW_FILE for key in map(path_key, paths) if key not in seen}, root)


def lookup(cfg: dict, path: str | os.PathLike[str]) -> Snapshot | None:
    session_id = cfg.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    root = cfg.get("state_root")
    try:
        digest = entries(session_id, root).get(path_key(path))
    except (OSError, ValueError):
        return None
    if not digest or digest == NEW_FILE:
        return None
    try:
        text = (_store(session_id, root) / digest).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        text = None
    return Snapshot(digest, text)
