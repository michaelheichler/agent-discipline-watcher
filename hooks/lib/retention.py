from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import session_state

MAX_AGE_SECONDS = 30 * 24 * 60 * 60
LOCK_FILENAME = ".retention.lock"


def _row_timestamp(row: dict) -> float | None:
    value = row.get("ts")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def _referenced_reports(row: object, reports_root: Path) -> set[Path]:
    found: set[Path] = set()
    if isinstance(row, dict):
        for value in row.values():
            found.update(_referenced_reports(value, reports_root))
    elif isinstance(row, list):
        for value in row:
            found.update(_referenced_reports(value, reports_root))
    elif isinstance(row, str):
        path = Path(row)
        try:
            resolved = path.resolve()
            if resolved.is_relative_to(reports_root.resolve()):
                found.add(resolved)
        except OSError:
            pass
    return found


def _is_kept(row: dict, cutoff: float, live: frozenset[str]) -> bool:
    session_id = row.get("session_id")
    if isinstance(session_id, str) and session_id in live:
        return True
    timestamp = _row_timestamp(row)
    return timestamp is None or timestamp >= cutoff


def _compact_ledger(path: Path, cutoff: float, live: frozenset[str], reports: Path) -> set[Path]:
    if not path.exists():
        return set()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    kept_reports: set[Path] = set()
    try:
        with path.open("r", encoding="utf-8") as source, os.fdopen(descriptor, "w", encoding="utf-8") as target:
            for line in source:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    target.write(line)
                    continue
                if not isinstance(row, dict) or _is_kept(row, cutoff, live):
                    target.write(line)
                    kept_reports.update(_referenced_reports(row, reports))
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return kept_reports


def _remove_old_files(root: Path, cutoff: float, keep: set[Path] = set()) -> None:
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_dir() or path.resolve() in keep:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _preserved_reports(reports: Path, live: frozenset[str]) -> set[Path]:
    kept: set[Path] = set()
    for session_id in live:
        kept.update(reports.glob(f"{session_id}-*.json"))
    return kept


def sweep(
    *,
    state_root: str | os.PathLike[str] | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
    data_root: str | os.PathLike[str] | None = None,
    now: float | None = None,
) -> None:
    current = time.time() if now is None else now
    state = Path(state_root) if state_root is not None else session_state.plugin_data_home() / "state"
    data = Path(data_root) if data_root is not None else state.parent
    ledger = Path(ledger_root) if ledger_root is not None else data / "ledger"
    reports = data / "reports"
    lock_path = data / LOCK_FILENAME
    data.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        cutoff = current - MAX_AGE_SECONDS
        live = session_state.live_session_ids(state, current)
        session_state.sweep_stale(MAX_AGE_SECONDS, state, current)
        kept = _compact_ledger(ledger / "ledger.jsonl", cutoff, live, reports)
        kept.update(_preserved_reports(reports, live))
        _remove_old_files(reports, cutoff, kept)
        _remove_old_files(data / "cache", cutoff)
        _remove_old_files(data / "logs", cutoff)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
