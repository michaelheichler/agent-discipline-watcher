"""Refcounted because loading the model per subagent would reload it thousands of times in one session."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from .session_state import _validate_session_id, plugin_data_home
except ImportError:
    from session_state import _validate_session_id, plugin_data_home

LEASE_TTL_SECONDS = 900
LEASE_SUFFIX = ".lease.json"


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
    if not isinstance(row, dict) or not isinstance(row.get("renewed_at"), (int, float)):
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


def acquire(session_id: str, now: float, root: str | os.PathLike[str] | None) -> None:
    directory = lease_root(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = _lease_path(directory, session_id)
    payload = json.dumps({"session_id": session_id, "pid": os.getpid(), "renewed_at": now})
    temporary = path.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


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
    """Sweeps as it reads, because a crashed session would otherwise pin the model forever."""
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
