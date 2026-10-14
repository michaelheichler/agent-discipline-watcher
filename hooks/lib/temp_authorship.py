"""Authored temp paths live in an append-only file, because a capped list let an evicted source pass as imported."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import NamedTuple

from lib import session_state
from lib.temp_copies import Cwd, source_key
from lib.temp_scope import outside_project_temp

AUTHORED_FILENAME = "authored_temp.jsonl"
MALFORMED_MARKER = "authored_temp.malformed-noticed"
LEGACY_KEYS = ("authored_temp", "authored_temp_overflow")
MAX_LINES = 200_000
MIN_LINE_BYTES = 4
FULL_REASON = (
    f"Scratch provenance for this session is full ({MAX_LINES:,} paths). "
    "Write to a project path or start a new session."
)
MALFORMED_NOTICE = (
    "agent-discipline-watcher: {count} damaged lines in the scratch provenance file were skipped. "
    "A copy of those temp files counts as imported."
)


class StoreRead(NamedTuple):
    keys: list[str]
    malformed: int


def _read(store: Path) -> StoreRead:
    """JSON per line, because a path may contain a newline and must not split into two authored entries."""
    try:
        lines = store.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return StoreRead([], 0)
    keys: list[str] = []
    malformed = 0
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(value, str):
            keys.append(value)
        else:
            malformed += 1
    return StoreRead(keys, malformed)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view):]


def _last_byte(store: Path) -> bytes:
    with store.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1)


def _append_locked(directory: Path, keys: list[str]) -> None:
    """Never capped here, because a dropped path would let its copy pass as imported."""
    store = directory / AUTHORED_FILENAME
    seen = set(_read(store).keys)
    fresh = [key for key in dict.fromkeys(keys) if key not in seen]
    if not fresh:
        return
    descriptor = os.open(store, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        torn = os.fstat(descriptor).st_size > 0 and _last_byte(store) != b"\n"
        lines = "".join(json.dumps(key) + "\n" for key in fresh)
        _write_all(descriptor, (("\n" if torn else "") + lines).encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append(directory: Path, keys: list[str]) -> None:
    lock_fd = os.open(directory / session_state.LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _append_locked(directory, keys)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def note_authored_temp(session_id: str, paths: list[str], cwd: Cwd, root: Cwd) -> None:
    """Errors propagate, because record must hold the turn rather than lose a provenance entry."""
    keys = [source_key(path, cwd) for path in paths]
    if not session_id or not keys:
        return
    directory = session_state.session_directory(session_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    _append(directory, keys)


def _migrate(session_id: str, directory: Path, root: Cwd) -> None:
    """Appended before the pop, so a crash between the two steps loses no authored path."""
    state = session_state.read_state(session_id, root)
    stored = state.get(LEGACY_KEYS[0])
    if isinstance(stored, list):
        _append(directory, [value for value in stored if isinstance(value, str)])
    if any(key in state for key in LEGACY_KEYS):
        session_state.update_state(
            session_id, lambda state: {key: value for key, value in state.items() if key not in LEGACY_KEYS}, root,
        )


def _directory(session_id: str, root: Cwd) -> Path | None:
    if not session_id:
        return None
    directory = session_state.session_directory(session_id, root)
    return directory if directory.is_dir() else None


def authored_temp(session_id: str, root: Cwd) -> frozenset[str]:
    directory = _directory(session_id, root)
    if directory is None:
        return frozenset()
    _migrate(session_id, directory, root)
    return frozenset(_read(directory / AUTHORED_FILENAME).keys)


def take_malformed_notice(session_id: str, root: Cwd) -> str:
    """Claimed once by marker file, because the same damaged lines would repeat on every call."""
    directory = _directory(session_id, root)
    if directory is None:
        return ""
    malformed = _read(directory / AUTHORED_FILENAME).malformed
    if not malformed:
        return ""
    try:
        os.close(os.open(directory / MALFORMED_MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return ""
    return MALFORMED_NOTICE.format(count=malformed)


def _full(directory: Path) -> bool:
    store = directory / AUTHORED_FILENAME
    try:
        size = store.stat().st_size
    except FileNotFoundError:
        return False
    if size < MAX_LINES * MIN_LINE_BYTES:
        return False
    return len(_read(store).keys) >= MAX_LINES


def scratch_refusal(session_id: str, paths: list[str], cwd: Cwd, root: Cwd) -> str:
    """Refused before the write, because past the cap a new scratch file must not lose its provenance."""
    if not any(outside_project_temp(path, cwd) for path in paths):
        return ""
    directory = _directory(session_id, root)
    return FULL_REASON if directory is not None and _full(directory) else ""
