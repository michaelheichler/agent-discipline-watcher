"""The Stop rescan stops at a deadline, because a hook the host kills after 10 seconds releases the turn unchecked."""
from __future__ import annotations

import math
import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from . import imported_baseline, scan_input
from .baseline import (
    OutOfTime, baseline_mode, fits_deadline, remaining, split_fallback_with_snapshot, split_with_snapshot,
)
from .config import resolve_outcome
from .imported_baseline import Snapshot
from .scanner import read_scannable, scan_all
from .temp_scope import outside_project_temp

STOP_SCAN_SECONDS = 7.0
MAX_NAMED_SKIPPED = 3
INHERITED_FIELD = "inherited"
Split = Callable[[dict], tuple[list[dict], list[dict]]]


@dataclass(slots=True)
class Rescan:
    findings: list[dict] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def deadline() -> float:
    return time.monotonic() + STOP_SCAN_SECONDS


def _resolved(raw_path: str, cwd: Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else cwd / path


def _tagged(split: Split, cfg: dict) -> list[dict]:
    """Tagged, because only own findings outlast the stall release."""
    if baseline_mode(cfg) != "none":
        return split(cfg)[0]
    owned, inherited = split({**cfg, "baseline": "report"})
    return [*owned, *({**row, INHERITED_FIELD: True} for row in inherited)]


def _path_rows(path: Path, cfg: dict, snapshot: Snapshot | None, until: float) -> list[dict]:
    """Reads and scans only, because the alarm can stop it at any line and a cut state write would lose blockers."""
    text = read_scannable(path, cfg)
    remaining(until)
    if text is None:
        stamp = path.stat()
        found = scan_input.fallback_findings(path)
        remaining(until)
        rows = _tagged(lambda mode: split_fallback_with_snapshot(path, found, mode, snapshot, until=until), cfg)
        digest = f"{stamp.st_size}:{stamp.st_mtime_ns}"
    else:
        fits_deadline(text, lambda: remaining(until))
        found = scan_all(str(path), text, cfg)
        remaining(until)
        rows = _tagged(lambda mode: split_with_snapshot(path, found, mode, snapshot, text, until=until), cfg)
        digest = sha256(text.encode("utf-8")).hexdigest()
    return [{**row, "content_hash": digest, "path": str(path)} for row in rows if resolve_outcome(row, cfg) == "block"]


def _owned_rows(path: Path, cwd: Path, cfg: dict, until: float) -> list[dict] | None:
    """None for a missing or temp path, because the rescan neither scans nor stamps it."""
    remaining(until)
    if not path.is_file() or outside_project_temp(path, cwd):
        return None
    snapshot = imported_baseline.lookup(cfg, path)
    with _alarm(until):
        return _path_rows(path, cfg, snapshot, until)


def _expire(_signum: int, _frame: object) -> None:
    raise OutOfTime


def _alarm_free() -> bool:
    """Because replacing an armed outer timer would postpone its earlier deadline, the size check alone bounds the scan then."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        return False
    return signal.getitimer(signal.ITIMER_REAL)[0] == 0


@contextmanager
def _alarm(until: float) -> Iterator[None]:
    """Because scan_all has no checkpoint, only a timer can stop it at the deadline, and SIGALRM reaches the main thread alone."""
    left = remaining(until)
    if math.isinf(left) or not _alarm_free():
        yield
        return
    previous = signal.signal(signal.SIGALRM, _expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, left)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def rescan(paths: list[str], cwd: Path, cfg: dict, until: float) -> Rescan:
    result = Rescan()
    for index, raw_path in enumerate(paths):
        path = _resolved(raw_path, cwd)
        try:
            rows = _owned_rows(path, cwd, cfg, until)
        except OutOfTime:
            result.skipped = [str(_resolved(raw, cwd)) for raw in paths[index:]]
            break
        if rows is not None:
            result.existing.append(str(path))
            result.findings.extend(rows)
    return result


def stamps(paths: list[str]) -> tuple[str, ...]:
    """Size and mtime, because the file was not read and an edit must still change the Stop fingerprint."""
    marks = []
    for path in paths:
        try:
            stat = Path(path).stat()
        except OSError:
            marks.append(f"{path}:missing")
            continue
        marks.append(f"{path}:{stat.st_size}:{stat.st_mtime_ns}")
    return tuple(marks)


def skipped_reason(skipped: list[str]) -> str:
    """Kept as a block, because a file the deadline cut off is unchecked, not clean."""
    names = ", ".join(Path(path).name for path in skipped[:MAX_NAMED_SKIPPED])
    more = f" and {len(skipped) - MAX_NAMED_SKIPPED} more" if len(skipped) > MAX_NAMED_SKIPPED else ""
    return (
        f"agent-discipline-watcher: Stop ran out of time. {len(skipped)} files not scanned: {names}{more}. "
        "They stay tracked for the next Stop."
    )
