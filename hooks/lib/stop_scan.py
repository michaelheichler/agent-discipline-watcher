"""The Stop rescan stops at a deadline, because a hook the host kills after 10 seconds releases the turn unchecked."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from . import scan_input
from .baseline import split_fallback, strip_committed
from .config import resolve_outcome
from .scanner import read_scannable, scan_all
from .temp_scope import outside_project_temp

STOP_SCAN_SECONDS = 7.0
MAX_NAMED_SKIPPED = 3


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


def _path_rows(path: Path, cfg: dict) -> list[dict]:
    text = read_scannable(path, cfg)
    if text is None:
        stamp = path.stat()
        rows = split_fallback(path, scan_input.fallback_findings(path), cfg)[0]
        digest = f"{stamp.st_size}:{stamp.st_mtime_ns}"
    else:
        rows = strip_committed(path, scan_all(str(path), text, cfg), cfg, text)
        digest = sha256(text.encode("utf-8")).hexdigest()
    return [{**row, "content_hash": digest, "path": str(path)} for row in rows if resolve_outcome(row, cfg) == "block"]


def rescan(paths: list[str], cwd: Path, cfg: dict, until: float) -> Rescan:
    result = Rescan()
    for index, raw_path in enumerate(paths):
        if time.monotonic() > until:
            result.skipped = [str(_resolved(raw, cwd)) for raw in paths[index:]]
            break
        path = _resolved(raw_path, cwd)
        if not path.is_file() or outside_project_temp(path, cwd):
            continue
        result.existing.append(str(path))
        result.findings.extend(_path_rows(path, cfg))
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
