"""Committed debt stays nonblocking because an edit should answer only for findings it introduced."""
from __future__ import annotations

import difflib
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

try:
    from . import imported_baseline
    from .config import FIXED_OBSERVE_RULES, SCANNER_ALWAYS_BLOCKING_RULES
    from .imported_baseline import Check, Snapshot, text_digest
    from .scan_input import CONTENT_SAMPLE_BYTES, has_generated_marker
    from .scanner import scan_all
except ImportError:
    import imported_baseline
    from config import FIXED_OBSERVE_RULES, SCANNER_ALWAYS_BLOCKING_RULES
    from imported_baseline import Check, Snapshot, text_digest
    from scan_input import CONTENT_SAMPLE_BYTES, has_generated_marker
    from scanner import scan_all


LENGTH_RULES = frozenset({"file_too_long", "unscannable_file"})
BASELINE_MODES = ("git", "report", "none")
DEFAULT_BASELINE_MODE = "report"
GIT_TIMEOUT_SECONDS = 2
MAX_BASELINE_CACHE = 256
BASELINE_SCAN_BYTES_PER_SECOND = 250_000
_BASELINE_CACHE: dict[tuple[str, str, int], tuple[dict, list[dict]]] = {}
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


def changed_lines(before: str, after: str) -> set[int]:
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    changed: set[int] = set()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, _old_start, _old_end, new_start, new_end in matcher.get_opcodes():
        if tag != "equal":
            changed.update(range(new_start + 1, new_end + 1))
    return changed


def finding_key(finding: dict) -> tuple[str, str, str]:
    """Identify a finding without its line number, so that an edit shifting a file does not resurface old debt."""
    return (
        str(finding.get("family", "")),
        str(finding.get("rule", "")),
        str(finding.get("snippet", "")).strip(),
    )


def rule_key(finding: dict) -> tuple[str, str]:
    return finding_key(finding)[:2]


def _consume(findings: list[dict], budget: Counter, key_of) -> list[dict]:
    kept = []
    for row in findings:
        key = key_of(row)
        if budget[key]:
            budget[key] -= 1
            continue
        kept.append(row)
    return kept


def subtract(findings: list[dict], baseline: list[dict]) -> list[dict]:
    """Drop the baseline's own findings, exact text first and rule alone second, because rewording an already offending line adds no debt."""
    exact = Counter(
        finding_key(row)
        for row in baseline
        if row.get("rule") not in SCANNER_ALWAYS_BLOCKING_RULES | FIXED_OBSERVE_RULES
    )
    survivors = _consume(findings, exact, finding_key)
    if not survivors:
        return []
    loose: Counter = Counter()
    for key, remaining in exact.items():
        loose[key[:2]] += remaining
    return _consume(survivors, loose, rule_key)


def partition(findings: list[dict], baseline: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep inherited findings separate because callers must surface them without turning them into blockers."""
    owned = subtract(findings, baseline)
    kept = {id(row) for row in owned}
    return owned, [row for row in findings if id(row) not in kept]


def _halves(findings: list[dict], baseline: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Withhold the inherited half outside report mode, because git mode promises silence about committed debt."""
    owned, inherited = partition(findings, baseline)
    return owned, inherited if baseline_mode(cfg) == "report" else []


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


def _fits_deadline(before: str, check: Check) -> None:
    """OutOfTime before the scan, because scan_all cannot stop midway and a 10 MB baseline outlasts the host Stop timeout."""
    left = check()
    if isinstance(left, float) and len(before) > left * BASELINE_SCAN_BYTES_PER_SECOND:
        raise OutOfTime


def _baseline_rows(path: Path, before: str, cfg: dict, check: Check) -> list[dict]:
    """Memoized per path and baseline hash, because a batch that edits one file twice scanned its baseline twice."""
    key = (str(path), text_digest(before, check), id(cfg))
    cached = _BASELINE_CACHE.get(key)
    if cached is not None and cached[0] is cfg:
        return cached[1]
    _fits_deadline(before, check)
    rows = scan_all(str(path), before, cfg)
    if len(_BASELINE_CACHE) >= MAX_BASELINE_CACHE:
        _BASELINE_CACHE.clear()
    _BASELINE_CACHE[key] = (cfg, rows)
    check()
    return rows


def _against(path: Path, findings: list[dict], cfg: dict, before: str, text: str | None, check: Check) -> tuple[list[dict], list[dict]]:
    owned, inherited = _length_relief(partition(findings, _baseline_rows(path, before, cfg, check)), before, text)
    return owned, inherited if baseline_mode(cfg) == "report" else []


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
    check = _deadline_check(until)
    snapshot = imported_baseline.lookup(cfg, path)
    split = None if snapshot is None else _split_snapshot(path, findings, cfg, snapshot, text, check)
    if split is not None:
        return split
    before = committed_text(path, until)
    if before is None:
        return findings, []
    return _against(path, findings, cfg, before, text, check)


def _head(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(CONTENT_SAMPLE_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _inherited_fallback(path: Path, cfg: dict, until: float | None) -> bool:
    check = _deadline_check(until)
    snapshot = imported_baseline.lookup(cfg, path)
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
    if not rows or baseline_mode(cfg) == "none" or not _inherited_fallback(path, cfg, until):
        return rows, []
    return [], rows if baseline_mode(cfg) == "report" else []


def split_against(texts: Texts, path: str, findings: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Pool every previous text because a merge resolution may take a line from any parent."""
    present = [text for text in texts if text is not None]
    if not findings or not present or baseline_mode(cfg) == "none":
        return findings, []
    pooled = [row for text in present for row in scan_all(path, text, cfg)]
    return _halves(findings, pooled, cfg)


def strip_committed(
    path: Path, findings: list[dict], cfg: dict, text: str | None = None, *, until: float | None = None,
) -> list[dict]:
    return split_committed(path, findings, cfg, text, until=until)[0]


def strip_against(texts: Texts, path: str, findings: list[dict], cfg: dict) -> list[dict]:
    return split_against(texts, path, findings, cfg)[0]
