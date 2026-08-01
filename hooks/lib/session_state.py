"""On-disk per-session JSON state store shared by the discipline hooks."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

STATE_FILENAME = "state.json"
LOCK_FILENAME = ".lock"


def _default_root() -> Path:
    return Path.home() / ".agent-discipline" / "state"


def _validate_session_id(session_id: str) -> None:
    if not isinstance(session_id, str) or not session_id or session_id in (".", ".."):
        raise ValueError(f"unsafe session_id: {session_id!r}")
    if "/" in session_id or "\\" in session_id or "\x00" in session_id:
        raise ValueError(f"unsafe session_id: {session_id!r}")


def _session_directory(
    session_id: str, root: str | os.PathLike[str] | None
) -> Path:
    _validate_session_id(session_id)
    base = Path(root) if root is not None else _default_root()
    candidate = base / session_id
    # Containment check because a symlink planted at base/session_id redirects writes outside the root even with a safe id.
    resolved_base = base.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_base):
        raise ValueError(f"session_id escapes state root: {session_id!r}")
    return candidate


def read_state(
    session_id: str, root: str | os.PathLike[str] | None = None
) -> dict:
    """Return the session state dict, or {} when the file is missing, corrupt, or not a dict."""
    path = _session_directory(session_id, root) / STATE_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError):
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(
    session_id: str,
    data: dict,
    root: str | os.PathLike[str] | None = None,
) -> None:
    """Atomically replace the session state file using a temp file plus os.replace."""
    directory = _session_directory(session_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / STATE_FILENAME
    payload = json.dumps(data, ensure_ascii=True)
    descriptor, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=".state.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def update_state(
    session_id: str,
    mutate: Callable[[dict], dict],
    root: str | os.PathLike[str] | None = None,
) -> dict:
    """Read-modify-write the session state under one exclusive flock and return the new dict."""
    directory = _session_directory(session_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    # Lock a separate .lock file because os.replace swaps state.json to a new inode, orphaning any flock on the old one.
    lock_fd = os.open(directory / LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            current = read_state(session_id, root)
            updated = mutate(current)
            if not isinstance(updated, dict):
                raise TypeError("update mutate must return a dict")
            write_state(session_id, updated, root)
            return updated
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def cleanup_session(
    session_id: str, root: str | os.PathLike[str] | None = None
) -> None:
    """Remove the session directory and every file inside it, ignoring a missing directory."""
    shutil.rmtree(_session_directory(session_id, root), ignore_errors=True)


def _remove_if_stale(entry: Path, cutoff: float) -> bool:
    try:
        mtime = entry.stat().st_mtime
    except OSError:
        return False
    if mtime >= cutoff:
        return False
    # Swallow rmtree errors because another process may be writing here, leaving the dir for the next sweep.
    try:
        shutil.rmtree(entry)
    except OSError:
        return False
    return not entry.exists()


def sweep_stale(
    max_age_seconds: float,
    root: str | os.PathLike[str] | None = None,
    now: float | None = None,
) -> int:
    """Remove session directories whose mtime predates the cutoff and return the count removed, where mtime is only a proxy so a live session that has not written within max_age is removed too."""
    base = Path(root) if root is not None else _default_root()
    if not base.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed = 0
    for entry in base.iterdir():
        if entry.is_dir() and _remove_if_stale(entry, cutoff):
            removed += 1
    return removed
