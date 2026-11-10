"""Refcounted because loading the model per subagent would reload it thousands of times in one session."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

try:
    from . import state_recovery
except ImportError:
    import state_recovery

try:
    from .process_records import Identity, identity, process_start, start_times
    from .session_state import _validate_session_id, plugin_data_home
except ImportError:
    from process_records import Identity, identity, process_start, start_times
    from session_state import _validate_session_id, plugin_data_home
LEASE_TTL_SECONDS = 900
LEASE_SUFFIX = ".lease.json"
LEASE_DIRECTORY = "embedding-leases"
ROOTS_DIRECTORY = "lease-roots"
ROOT_SUFFIX = ".root"


def lease_root(root: str | os.PathLike[str] | None) -> Path:
    return Path(root) if root is not None else plugin_data_home() / LEASE_DIRECTORY


def _lease_path(directory: Path, session_id: str) -> Path:
    _validate_session_id(session_id)
    return directory / (session_id + LEASE_SUFFIX)


def read_lease(path: Path) -> dict | None:
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


def _is_live(row: dict, now: float, starts: dict[int, str | None]) -> bool:
    """Unknown ownership counts as alive, because evicting a foreign session costs more than a late unload."""
    if now - float(row["renewed_at"]) > LEASE_TTL_SECONDS:
        return False
    return identity(row, starts=starts) != Identity.MISMATCH


def acquire(session_id: str, now: float, root: str | os.PathLike[str] | None, owner_pid: int) -> None:
    """Caller pid, because the hook pid dies within the second."""
    directory = lease_root(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = _lease_path(directory, session_id)
    started = process_start(owner_pid)
    state_recovery.atomic_json(path, {
        "session_id": session_id, "pid": owner_pid, "process_start": started, "renewed_at": now,
    }, ensure_ascii=True, mode=None)


def renew(session_id: str, now: float, root: str | os.PathLike[str] | None) -> bool:
    """A turn past the TTL would otherwise lose the model."""
    path = _lease_path(lease_root(root), session_id)
    row = read_lease(path)
    if row is None:
        return False
    state_recovery.atomic_json(
        path, {**row, "session_id": session_id, "renewed_at": now}, ensure_ascii=True, mode=None,
    )
    return True


def release(session_id: str, root: str | os.PathLike[str] | None) -> bool:
    path = _lease_path(lease_root(root), session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _discard(path: Path) -> None:
    """Swallowed because a concurrent sweep removing the same stale lease is the expected race, not a failure."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _lease_rows(directory: Path) -> list[tuple[Path, dict | None]]:
    return [(path, read_lease(path)) for path in sorted(directory.glob("*" + LEASE_SUFFIX))]


def _sweep(rows: list[tuple[Path, dict | None]], now: float, starts: dict[int, str | None]) -> tuple[str, ...]:
    found = []
    for path, row in rows:
        if row is None or not _is_live(row, now, starts):
            _discard(path)
        else:
            found.append(str(row.get("session_id", path.name[:-len(LEASE_SUFFIX)])))
    return tuple(found)


def live_sessions(now: float, root: str | os.PathLike[str] | None) -> tuple[str, ...]:
    """Sweeps because a crashed session would pin the model."""
    rows = _lease_rows(lease_root(root))
    starts = start_times([row.get("pid") for _, row in rows if row is not None])
    return _sweep(rows, now, starts)


def register_root(server_root: Path, root: str | os.PathLike[str] | None) -> None:
    """Track all project lease roots because they share one machine-wide worker; callers hold its lifecycle lock."""
    directory = server_root / ROOTS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    resolved = str(lease_root(root).resolve())
    name = hashlib.sha256(resolved.encode("utf-8")).hexdigest()
    registration = directory / (name + ROOT_SUFFIX)
    state_recovery.atomic_write(registration, resolved, mode=None)


def registered_roots(server_root: Path) -> list[Path]:
    """Validate registration names because cleanup must not follow forged lease pointers."""
    found = []
    for registration in sorted((server_root / ROOTS_DIRECTORY).glob("*" + ROOT_SUFFIX)):
        text = registration.read_text(encoding="utf-8")
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest() + ROOT_SUFFIX
        directory = Path(text)
        if registration.name != expected or not directory.is_absolute():
            raise RuntimeError(f"invalid embedding lease registration: {registration}")
        found.append(directory)
    return found


def has_live_leases(server_root: Path, now: float) -> bool:
    """Batch identities because lifecycle callers wait for the entire sweep."""
    rows = []
    for directory in registered_roots(server_root):
        if directory.exists():
            rows.extend(_lease_rows(directory))
        else:
            name = hashlib.sha256(str(directory).encode("utf-8")).hexdigest() + ROOT_SUFFIX
            (server_root / ROOTS_DIRECTORY / name).unlink(missing_ok=True)
    starts = start_times([row.get("pid") for _, row in rows if row is not None])
    return bool(_sweep(rows, now, starts))
