"""Committed debt stays nonblocking because an edit should answer only for findings it introduced."""
from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

try:
    from . import imported_baseline
    from .imported_baseline import Check, Snapshot, text_digest
    from .provenance import OWNED_RULES, Provenance, compare_any
    from .regular_file import open_regular, read_regular_text
    from .scan_input import CONTENT_SAMPLE_BYTES, has_generated_marker
except ImportError:
    import imported_baseline
    from imported_baseline import Check, Snapshot, text_digest
    from provenance import OWNED_RULES, Provenance, compare_any
    from regular_file import open_regular, read_regular_text
    from scan_input import CONTENT_SAMPLE_BYTES, has_generated_marker


LENGTH_RULES = frozenset({"file_too_long", "unscannable_file"})
BASELINE_MODES = ("git", "report", "none")
DEFAULT_BASELINE_MODE = "report"
GIT_TIMEOUT_SECONDS = 2
BASELINE_SCAN_BYTES_PER_SECOND = 250_000
Texts = Sequence[str | None]


def baseline_mode(cfg: dict) -> str:
    """Report inherited debt by default because silently hiding it prevents incremental cleanup."""
    mode = cfg.get("baseline")
    return mode if mode in BASELINE_MODES else DEFAULT_BASELINE_MODE


class OutOfTime(Exception):
    """Raised instead of returning None, because a baseline the deadline cut off is unknown, not absent."""


def remaining(until: float | None) -> float | None:
    if until is None:
        return None
    left = until - time.monotonic()
    if left <= 0:
        raise OutOfTime
    return left


def _git(args: list[str], cwd: Path, until: float | None = None) -> str | None:
    left = remaining(until)
    timeout = GIT_TIMEOUT_SECONDS if left is None else min(GIT_TIMEOUT_SECONDS, left)
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True, capture_output=True,
            check=True, timeout=timeout, errors="replace",
        )
    except subprocess.TimeoutExpired:
        remaining(until)
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _repo_relative(path: Path, until: float | None) -> tuple[Path, str] | None:
    directory = path.parent
    if not directory.is_dir():
        return None
    top = _git(["rev-parse", "--show-toplevel"], directory, until)
    if not top or not top.strip():
        return None
    try:
        relative = path.resolve().relative_to(Path(top.strip()).resolve())
    except (OSError, ValueError):
        return None
    return directory, relative.as_posix()


def committed_text(path: Path, until: float | None = None) -> str | None:
    """OutOfTime past until, because the Stop rescan must not outlive the host's 10 second limit."""
    located = _repo_relative(path, until)
    if located is None:
        return None
    directory, relative = located
    return _git(["show", "HEAD:" + relative], directory, until)


def partition(findings: list[dict], provenance: Provenance) -> tuple[list[dict], list[dict]]:
    """Keep inherited findings separate because callers must surface them without turning them into blockers."""
    owned = [row for row in findings if provenance.owns(row)]
    kept = {id(row) for row in owned}
    return owned, [row for row in findings if id(row) not in kept]


def _line_count(text: str) -> int:
    return len(text.splitlines()) or 1


def _inherited_length(before: str, after: str | None) -> bool:
    """A marker must sit in the baseline too, because the agent could otherwise add one to escape the length rule."""
    if after is None:
        return False
    if _line_count(after) <= _line_count(before):
        return True
    return has_generated_marker(before) and has_generated_marker(after)


def _length_relief(halves: tuple[list[dict], list[dict]], before: str, after: str | None) -> tuple[list[dict], list[dict]]:
    """Kept owned only for a longer file, because an inherited long file is not the agent's to split."""
    owned, inherited = halves
    if not _inherited_length(before, after):
        return owned, inherited
    moved = [row for row in owned if row.get("rule") in LENGTH_RULES]
    return [row for row in owned if row.get("rule") not in LENGTH_RULES], inherited + moved


def _deadline_check(until: float | None) -> Check:
    return lambda: remaining(until)


def fits_deadline(text: str, check: Check) -> None:
    """OutOfTime before the scan, because off the main thread no alarm can stop scan_all midway."""
    left = check()
    if isinstance(left, float) and len(text) > left * BASELINE_SCAN_BYTES_PER_SECOND:
        raise OutOfTime


def _current(path: Path, text: str | None) -> str | None:
    if text is not None:
        return text
    try:
        return read_regular_text(path, errors="replace")
    except OSError:
        return None


def _owned_split(path: Path, findings: list[dict], befores: list[str], text: str | None, check: Check) -> tuple[list[dict], list[dict]]:
    """No diff when every rule stays owned, because the diff could not move a row."""
    current = _current(path, text)
    if current is None or all(row.get("rule") in OWNED_RULES for row in findings):
        return findings, []
    return partition(findings, compare_any(str(path), befores, current, check))


def _split_texts(path: Path, findings: list[dict], cfg: dict, befores: list[str], text: str | None, check: Check) -> tuple[list[dict], list[dict]]:
    """Relieved by any parent, because a merge may take the long file whole from one."""
    relieving = next((before for before in befores if _inherited_length(before, text)), befores[0])
    owned, inherited = _length_relief(_owned_split(path, findings, befores, text, check), relieving, text)
    return owned, inherited if baseline_mode(cfg) == "report" else []


def _against(path: Path, findings: list[dict], cfg: dict, before: str, text: str | None, check: Check) -> tuple[list[dict], list[dict]]:
    return _split_texts(path, findings, cfg, [before], text, check)


def _split_snapshot(
    path: Path, findings: list[dict], cfg: dict, snapshot: Snapshot, text: str | None, check: Check,
) -> tuple[list[dict], list[dict]] | None:
    if text is not None and text_digest(text, check) == snapshot.digest:
        return [], findings if baseline_mode(cfg) == "report" else []
    before = snapshot.read(check)
    if before is None:
        return None
    return _against(path, findings, cfg, before, text, check)


def split_committed(
    path: Path, findings: list[dict], cfg: dict, text: str | None = None, *, until: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Compare against HEAD because blocking on findings that predate an edit would prevent incremental cleanup."""
    if not findings or baseline_mode(cfg) == "none":
        return findings, []
    return split_with_snapshot(path, findings, cfg, imported_baseline.lookup(cfg, path), text, until=until)


def split_with_snapshot(
    path: Path, findings: list[dict], cfg: dict, snapshot: Snapshot | None, text: str | None = None, *,
    until: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Because the snapshot lookup can write session state, the Stop rescan runs it before it arms the alarm."""
    if not findings or baseline_mode(cfg) == "none":
        return findings, []
    check = _deadline_check(until)
    split = None if snapshot is None else _split_snapshot(path, findings, cfg, snapshot, text, check)
    if split is not None:
        return split
    before = committed_text(path, until)
    if before is None:
        return findings, []
    return _against(path, findings, cfg, before, text, check)


def _head(path: Path) -> str:
    try:
        with open_regular(path) as handle:
            return handle.read(CONTENT_SAMPLE_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _inherited_fallback(path: Path, snapshot: Snapshot | None, until: float | None) -> bool:
    check = _deadline_check(until)
    if snapshot is not None and imported_baseline.file_digest(path, check) == snapshot.digest:
        return True
    if not has_generated_marker(_head(path)):
        return False
    before = None if snapshot is None else snapshot.read(check)
    if before is None:
        before = committed_text(path, until)
    return before is not None and has_generated_marker(before)


def split_fallback(path: Path, rows: list[dict], cfg: dict, *, until: float | None = None) -> tuple[list[dict], list[dict]]:
    """Unscannable rows stay advice for an unchanged import or an inherited generated file, because the agent wrote neither."""
    if not rows or baseline_mode(cfg) == "none":
        return rows, []
    return split_fallback_with_snapshot(path, rows, cfg, imported_baseline.lookup(cfg, path), until=until)


def split_fallback_with_snapshot(
    path: Path, rows: list[dict], cfg: dict, snapshot: Snapshot | None, *, until: float | None = None,
) -> tuple[list[dict], list[dict]]:
    if not rows or baseline_mode(cfg) == "none" or not _inherited_fallback(path, snapshot, until):
        return rows, []
    return [], rows if baseline_mode(cfg) == "report" else []


def split_against(texts: Texts, path: str, findings: list[dict], cfg: dict, text: str) -> tuple[list[dict], list[dict]]:
    """Owned only where every parent differs, because a merge resolution may take a line from any parent."""
    present = [before for before in texts if before is not None]
    if not findings or not present or baseline_mode(cfg) == "none":
        return findings, []
    return _split_texts(Path(path), findings, cfg, present, text, _deadline_check(None))


def strip_committed(
    path: Path, findings: list[dict], cfg: dict, text: str | None = None, *, until: float | None = None,
) -> list[dict]:
    return split_committed(path, findings, cfg, text, until=until)[0]


def strip_against(texts: Texts, path: str, findings: list[dict], cfg: dict, text: str) -> list[dict]:
    return split_against(texts, path, findings, cfg, text)[0]
