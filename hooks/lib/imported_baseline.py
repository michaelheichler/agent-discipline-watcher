"""Content the agent did not write gets a session baseline, because git cannot vouch for copied or untracked files."""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from functools import cached_property
from pathlib import Path
from typing import BinaryIO

try:
    from . import session_state
except ImportError:
    import session_state

STATE_KEY = "imported_baseline"
STORE_DIRNAME = "imported"
INDEX_DIRNAME = "paths"
GIT_BASELINE = ""
NEW_FILE = "new"
BLOCK_BYTES = 1 << 16
_MIGRATED: set[tuple[str, str]] = set()
Check = Callable[[], object]


def _unchecked() -> None:
    return None


def _blocks(handle: BinaryIO, check: Check) -> Iterator[bytes]:
    """Checked per block, because a Stop deadline must cut off a large file mid-read."""
    for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
        check()
        yield block


@dataclass(frozen=True)
class Snapshot:
    digest: str
    blob: Path

    @cached_property
    def text(self) -> str | None:
        """Read on demand, because most callers only compare the digest and a blob has no size limit."""
        return self.read()

    def read(self, check: Check = _unchecked) -> str | None:
        try:
            with self.blob.open("rb") as handle:
                data = b"".join(_blocks(handle, check))
        except OSError:
            return None
        return data.decode("utf-8", errors="replace")


def path_key(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(os.path.expanduser(os.fspath(path)))


def _stream_digest(handle: BinaryIO, check: Check) -> str:
    digest = hashlib.sha256()
    for block in _blocks(handle, check):
        digest.update(block)
    return digest.hexdigest()


def file_digest(path: str | os.PathLike[str], check: Check = _unchecked) -> str | None:
    try:
        with open(path, "rb") as handle:
            return _stream_digest(handle, check)
    except OSError:
        return None


def text_digest(text: str, check: Check = _unchecked) -> str:
    data = memoryview(text.encode("utf-8", errors="surrogatepass"))
    digest = hashlib.sha256()
    for start in range(0, len(data), BLOCK_BYTES):
        check()
        digest.update(data[start:start + BLOCK_BYTES])
    return digest.hexdigest()


def _store(session_id: str, root: str | os.PathLike[str] | None) -> Path:
    return session_state.session_directory(session_id, root) / STORE_DIRNAME


def _index_file(index: Path, key: str) -> Path:
    return index / text_digest(key)


def _read_mark(index: Path, key: str) -> str | None:
    try:
        return _index_file(index, key).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _put_mark(index: Path, key: str, mark: str, *, replace: bool) -> bool:
    """Linked when not replacing, because two hooks can see one file first at once and the first sight must win."""
    index.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=index, prefix=".mark.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(mark)
        if replace:
            os.replace(temporary, _index_file(index, key))
            return True
        try:
            os.link(temporary, _index_file(index, key))
        except FileExistsError:
            return False
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


def _legacy_entries(state: dict) -> dict[str, str]:
    stored = state.get(STATE_KEY)
    if not isinstance(stored, dict):
        return {}
    return {key: value for key, value in stored.items() if isinstance(key, str) and isinstance(value, str)}


def _migrate(session_id: str, index: Path, root: str | os.PathLike[str] | None) -> None:
    """Copied before the pop, so a session that began on the state.json map keeps every baseline."""
    state = session_state.read_state(session_id, root)
    if STATE_KEY not in state:
        return
    for key, mark in _legacy_entries(state).items():
        _put_mark(index, key, mark, replace=False)
    session_state.update_state(
        session_id, lambda current: {name: value for name, value in current.items() if name != STATE_KEY}, root,
    )


def _index(session_id: str, root: str | os.PathLike[str] | None) -> Path:
    """One file per path instead of a state.json map, because every state write rewrites the map and a cap on it dropped baselines."""
    index = _store(session_id, root) / INDEX_DIRNAME
    marker = (session_id, str(index))
    if marker not in _MIGRATED:
        _migrate(session_id, index, root)
        _MIGRATED.add(marker)
    return index


def _hashed_copy(source: BinaryIO, target: BinaryIO) -> str:
    """Hashed while copied, so the blob name always matches the bytes it holds."""
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1 << 16), b""):
        digest.update(block)
        target.write(block)
    return digest.hexdigest()


def _copied_blob(source: BinaryIO, store: Path) -> str:
    store.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=store, prefix=".blob.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            digest = _hashed_copy(source, handle)
        if not (store / digest).exists():
            os.replace(temporary, store / digest)
        return digest
    finally:
        Path(temporary).unlink(missing_ok=True)


def _captured(path: Path, store: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        source = path.open("rb")
    except OSError:
        return None
    with source:
        return _copied_blob(source, store)


def snapshot_many(session_id: str, paths: list[str], root: str | os.PathLike[str] | None) -> list[str]:
    """Return the keys whose baseline is new, so an identical re-import reports nothing twice."""
    if not session_id:
        return []
    store = _store(session_id, root)
    index = _index(session_id, root)
    changed: list[str] = []
    for key in dict.fromkeys(map(path_key, paths)):
        digest = _captured(Path(key), store)
        if digest is not None and _read_mark(index, key) != digest:
            _put_mark(index, key, digest, replace=True)
            changed.append(key)
    return changed


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
    store = _store(session_id, root)
    index = _index(session_id, root)
    for key in dict.fromkeys(map(path_key, paths)):
        mark = None if _read_mark(index, key) is not None else _first_mark(Path(key), store, has_git)
        if mark is not None:
            _put_mark(index, key, mark, replace=False)


def note_written(session_id: str, paths: list[str], root: str | os.PathLike[str] | None) -> None:
    """Claimed after a write nobody saw first, because a later first sight must not baseline the agent's own text."""
    if not session_id:
        return
    index = _index(session_id, root)
    for key in dict.fromkeys(map(path_key, paths)):
        _put_mark(index, key, NEW_FILE, replace=False)


def lookup(cfg: dict, path: str | os.PathLike[str]) -> Snapshot | None:
    session_id = cfg.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    root = cfg.get("state_root")
    try:
        digest = _read_mark(_index(session_id, root), path_key(path))
    except (OSError, ValueError):
        return None
    if not digest or digest == NEW_FILE:
        return None
    return Snapshot(digest, _store(session_id, root) / digest)
