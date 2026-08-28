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
DATA_DIRNAME = ".adw"
LEGACY_DATA_DIRNAME = ".agent-discipline"
SESSION_LEASE_DIRNAME = "session-leases"
SESSION_LEASE_SUFFIX = ".lease.json"
SESSION_LEASE_TTL_SECONDS = 900


def plugin_data_home() -> Path:
    """One root for every install, because a host-supplied data directory used to split reports away from state and leases."""
    home = Path.home() / DATA_DIRNAME
    legacy = Path.home() / LEGACY_DATA_DIRNAME
    if not home.exists() and legacy.is_dir():
        legacy.rename(home)
    return home


def models_root() -> Path:
    return plugin_data_home() / "models"


def _default_root() -> Path:
    return plugin_data_home() / "state"


def session_lease_root(root: str | os.PathLike[str] | None = None) -> Path:
    state_root = Path(root) if root is not None else _default_root()
    return state_root.with_name(SESSION_LEASE_DIRNAME)


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


def read_state_strict(
    session_id: str, root: str | os.PathLike[str] | None = None
) -> dict:
    path = _session_directory(session_id, root) / STATE_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"invalid session state object: {path}")
    return data


def write_state(
    session_id: str,
    data: dict,
    root: str | os.PathLike[str] | None = None,
) -> None:
    """Replace the file atomically because separate hook processes must never observe partial JSON."""
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


def _update_state_with_lock(
    lock_fd: int,
    session_id: str,
    mutate: Callable[[dict], dict],
    root: str | os.PathLike[str] | None,
) -> dict:
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


def update_state(
    session_id: str,
    mutate: Callable[[dict], dict],
    root: str | os.PathLike[str] | None = None,
) -> dict:
    """Hold one lock across reading and writing because concurrent hook processes would otherwise lose updates."""
    directory = _session_directory(session_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    # Lock a separate .lock file because os.replace swaps state.json to a new inode, orphaning any flock on the old one.
    lock_fd = os.open(directory / LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        return _update_state_with_lock(lock_fd, session_id, mutate, root)
    finally:
        os.close(lock_fd)


def update_state_strict(
    session_id: str,
    mutate: Callable[[dict], dict],
    root: str | os.PathLike[str] | None = None,
) -> dict:
    directory = _session_directory(session_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(directory / LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        current = read_state_strict(session_id, root)
        updated = mutate(current)
        if not isinstance(updated, dict):
            raise TypeError("update mutate must return a dict")
        write_state(session_id, updated, root)
        return updated
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _next_turn(state: dict) -> dict:
    count = state.get("turn_count")
    if not isinstance(count, int) or isinstance(count, bool):
        count = 0
    count += 1
    return {**state, "turn_count": count, "turn_id": f"turn-{count}"}


def advance_turn(
    session_id: str, root: str | os.PathLike[str] | None = None
) -> dict:
    """Raise instead of resetting a corrupt state file, because a lifecycle caller that owns the turn boundary must not erase unresolved_blockers by accident."""
    return update_state_strict(session_id, _next_turn, root)


def cleanup_session(
    session_id: str, root: str | os.PathLike[str] | None = None
) -> None:
    shutil.rmtree(_session_directory(session_id, root), ignore_errors=True)


def _session_lease_path(
    session_id: str, root: str | os.PathLike[str] | None = None,
) -> Path:
    _validate_session_id(session_id)
    return session_lease_root(root) / f"{session_id}{SESSION_LEASE_SUFFIX}"


def acquire_session_lease(
    session_id: str,
    root: str | os.PathLike[str] | None = None,
    now: float | None = None,
) -> None:
    path = _session_lease_path(session_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{session_id}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"session_id": session_id, "renewed_at": time.time() if now is None else now}, handle)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def release_session_lease(
    session_id: str, root: str | os.PathLike[str] | None = None,
) -> None:
    _session_lease_path(session_id, root).unlink(missing_ok=True)


def live_session_ids(
    root: str | os.PathLike[str] | None = None,
    now: float | None = None,
) -> frozenset[str]:
    current = time.time() if now is None else now
    directory = session_lease_root(root)
    if not directory.is_dir():
        return frozenset()
    live: set[str] = set()
    for path in directory.glob(f"*{SESSION_LEASE_SUFFIX}"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            session_id = row.get("session_id") if isinstance(row, dict) else None
            renewed_at = row.get("renewed_at") if isinstance(row, dict) else None
            _validate_session_id(session_id)
            if not isinstance(renewed_at, (int, float)) or current - renewed_at > SESSION_LEASE_TTL_SECONDS:
                raise ValueError("expired session lease")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        live.add(session_id)
    return frozenset(live)


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
    """Sweeping on mtime accepts deleting a live session that has gone quiet, because no cheaper liveness signal exists on disk."""
    base = Path(root) if root is not None else _default_root()
    if not base.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max_age_seconds
    live = live_session_ids(root, now)
    removed = 0
    for entry in base.iterdir():
        if entry.is_dir() and entry.name not in live and _remove_if_stale(entry, cutoff):
            removed += 1
    return removed
