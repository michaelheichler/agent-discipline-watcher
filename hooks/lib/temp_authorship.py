"""Authored temp paths live in an append-only file, because a capped list let an evicted source pass as imported."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from lib import session_state
from lib.temp_copies import Cwd, source_key

AUTHORED_FILENAME = "authored_temp.jsonl"
OVERFLOW_FILENAME = "authored_temp.overflow"
LEGACY_KEYS = ("authored_temp", "authored_temp_overflow")
MAX_LINES = 200_000
OVERFLOW_NOTICE = (
    "agent-discipline-watcher: this session wrote more temp files than the provenance store holds. "
    "Every copy from temp now counts as your own and can block."
)


def _read(store: Path) -> list[str]:
    """JSON per line, because a path may contain a newline and must not split into two authored entries."""
    try:
        lines = store.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    keys = []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, str):
            keys.append(value)
    return keys


def _append_locked(directory: Path, keys: list[str]) -> bool:
    store = directory / AUTHORED_FILENAME
    known = _read(store)
    seen = set(known)
    fresh = [key for key in dict.fromkeys(keys) if key not in seen]
    room = max(MAX_LINES - len(known), 0)
    if fresh[:room]:
        with store.open("a", encoding="utf-8") as handle:
            # Newline first, so a line a crashed writer left open cannot eat this entry.
            handle.write("\n" + "".join(json.dumps(key) + "\n" for key in fresh[:room]))
    marker = directory / OVERFLOW_FILENAME
    if len(fresh) <= room or marker.exists():
        return False
    marker.touch()
    return True


def _append(directory: Path, keys: list[str]) -> bool:
    """True only for the call that hits the cap, so the notice shows once."""
    lock_fd = os.open(directory / session_state.LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return _append_locked(directory, keys)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def note_authored_temp(session_id: str, paths: list[str], cwd: Cwd, root: Cwd) -> str:
    """Remembered per session, because only a temp file the agent wrote can make its copy the agent's own."""
    keys = [source_key(path, cwd) for path in paths]
    if not session_id or not keys:
        return ""
    directory = session_state.session_directory(session_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    return OVERFLOW_NOTICE if _append(directory, keys) else ""


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


def authored_temp(session_id: str, root: Cwd) -> frozenset[str] | None:
    """None past the hard cap, because an unrecorded authored source would pass as imported."""
    if not session_id:
        return frozenset()
    directory = session_state.session_directory(session_id, root)
    if not directory.is_dir():
        return frozenset()
    _migrate(session_id, directory, root)
    if (directory / OVERFLOW_FILENAME).exists():
        return None
    return frozenset(_read(directory / AUTHORED_FILENAME))
