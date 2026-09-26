"""Refcounted because loading the model per subagent would reload it thousands of times in one session."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

try:
    from .session_state import _validate_session_id, plugin_data_home
except ImportError:
    from session_state import _validate_session_id, plugin_data_home

LEASE_TTL_SECONDS = 900
LEASE_SUFFIX = ".lease.json"
ROOTS_DIRECTORY = "lease-roots"
ROOT_SUFFIX = ".root"


def lease_root(root: str | os.PathLike[str] | None) -> Path:
    return Path(root) if root is not None else plugin_data_home() / "embedding-leases"


def _lease_path(directory: Path, session_id: str) -> Path:
    _validate_session_id(session_id)
    return directory / (session_id + LEASE_SUFFIX)


def _read_lease(path: Path) -> dict | None:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict) or type(row.get("renewed_at")) not in (int, float):
        return None
    try:
        if not math.isfinite(row["renewed_at"]):
            return None
    except OverflowError:
        return None
    return row


def _process_alive(pid: object) -> bool:
    """Unknown ownership counts as alive, because evicting a foreign session costs more than a late unload."""
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_live(row: dict, now: float) -> bool:
    if now - float(row["renewed_at"]) > LEASE_TTL_SECONDS:
        return False
    return _process_alive(row.get("pid"))


def acquire(session_id: str, now: float, root: str | os.PathLike[str] | None, owner_pid: int) -> None:
    """Caller pid, because the hook pid dies within the second."""
    directory = lease_root(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = _lease_path(directory, session_id)
    _write_lease(path, {"session_id": session_id, "pid": owner_pid, "renewed_at": now})


def _write_lease(path: Path, row: dict) -> None:
    payload = json.dumps(row)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def renew(session_id: str, now: float, root: str | os.PathLike[str] | None) -> bool:
    """A turn past the TTL would otherwise lose the model."""
    path = _lease_path(lease_root(root), session_id)
    row = _read_lease(path)
    if row is None:
        return False
    _write_lease(path, {**row, "session_id": session_id, "renewed_at": now})
    return True


def release(session_id: str, root: str | os.PathLike[str] | None) -> None:
    path = _lease_path(lease_root(root), session_id)
    path.unlink(missing_ok=True)


def _discard(path: Path) -> None:
    """Swallowed because a concurrent sweep removing the same stale lease is the expected race, not a failure."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _surviving_session(path: Path, now: float) -> str | None:
    row = _read_lease(path)
    if row is None or not _is_live(row, now):
        _discard(path)
        return None
    return str(row.get("session_id", path.name[: -len(LEASE_SUFFIX)]))


def live_sessions(now: float, root: str | os.PathLike[str] | None) -> tuple[str, ...]:
    """Sweeps because a crashed session would pin the model."""
    directory = lease_root(root)
    if not directory.is_dir():
        return ()
    found = (
        _surviving_session(path, now)
        for path in sorted(directory.glob("*" + LEASE_SUFFIX))
    )
    return tuple(name for name in found if name is not None)


def may_unload(session_id: str, now: float, root: str | os.PathLike[str] | None) -> bool:
    """Only the last live holder may unload, because another session mid-turn would lose the model underneath it."""
    release(session_id, root)
    return not live_sessions(now, root)


def register_root(server_root: Path, root: str | os.PathLike[str] | None) -> None:
    """Track all project lease roots because they share one machine-wide worker; callers hold its lifecycle lock."""
    directory = server_root / ROOTS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    resolved = str(lease_root(root).resolve())
    name = hashlib.sha256(resolved.encode("utf-8")).hexdigest()
    registration = directory / (name + ROOT_SUFFIX)
    temporary = registration.with_suffix(".tmp")
    temporary.write_text(resolved, encoding="utf-8")
    temporary.replace(registration)


def has_live_leases(server_root: Path, now: float) -> bool:
    """Sweeps because an idle root must not pin the worker."""
    found = False
    for registration in sorted((server_root / ROOTS_DIRECTORY).glob("*" + ROOT_SUFFIX)):
        directory = registration.read_text(encoding="utf-8")
        if live_sessions(now, directory):
            found = True
        else:
            registration.unlink(missing_ok=True)
    return found
