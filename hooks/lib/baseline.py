"""Committed debt stays nonblocking because an edit should answer only for findings it introduced."""
from __future__ import annotations

import difflib
import subprocess
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

try:
    from . import imported_baseline
    from .config import FIXED_OBSERVE_RULES, SCANNER_ALWAYS_BLOCKING_RULES
    from .imported_baseline import Snapshot, text_digest
    from .scanner import scan_all
except ImportError:
    import imported_baseline
    from config import FIXED_OBSERVE_RULES, SCANNER_ALWAYS_BLOCKING_RULES
    from imported_baseline import Snapshot, text_digest
    from scanner import scan_all


LENGTH_RULES = frozenset({"file_too_long", "unscannable_file"})
BASELINE_MODES = ("git", "report", "none")
DEFAULT_BASELINE_MODE = "report"
GIT_TIMEOUT_SECONDS = 10
Texts = Sequence[str | None]


def baseline_mode(cfg: dict) -> str:
    """Report inherited debt by default because silently hiding it prevents incremental cleanup."""
    mode = cfg.get("baseline")
    return mode if mode in BASELINE_MODES else DEFAULT_BASELINE_MODE


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True, capture_output=True,
            check=True, timeout=GIT_TIMEOUT_SECONDS, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _repo_relative(path: Path) -> tuple[Path, str] | None:
    directory = path.parent
    if not directory.is_dir():
        return None
    top = _git(["rev-parse", "--show-toplevel"], directory)
    if not top or not top.strip():
        return None
    try:
        relative = path.resolve().relative_to(Path(top.strip()).resolve())
    except (OSError, ValueError):
        return None
    return directory, relative.as_posix()


def committed_text(path: Path) -> str | None:
    located = _repo_relative(path)
    if located is None:
        return None
    directory, relative = located
    return _git(["show", "HEAD:" + relative], directory)


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


def _length_relief(halves: tuple[list[dict], list[dict]], before: str, after: str | None) -> tuple[list[dict], list[dict]]:
    """Kept owned only for a longer file, because an inherited long file is not the agent's to split."""
    owned, inherited = halves
    if after is None or _line_count(after) > _line_count(before):
        return owned, inherited
    moved = [row for row in owned if row.get("rule") in LENGTH_RULES]
    return [row for row in owned if row.get("rule") not in LENGTH_RULES], inherited + moved


def _split_snapshot(path: Path, findings: list[dict], cfg: dict, snapshot: Snapshot, text: str | None) -> tuple[list[dict], list[dict]] | None:
    if text is not None and text_digest(text) == snapshot.digest:
        return [], findings if baseline_mode(cfg) == "report" else []
    if snapshot.text is None:
        return None
    halves = _length_relief(partition(findings, scan_all(str(path), snapshot.text, cfg)), snapshot.text, text)
    return halves[0], halves[1] if baseline_mode(cfg) == "report" else []


def split_committed(path: Path, findings: list[dict], cfg: dict, text: str | None = None) -> tuple[list[dict], list[dict]]:
    """Compare against HEAD because blocking on findings that predate an edit would prevent incremental cleanup."""
    if not findings or baseline_mode(cfg) == "none":
        return findings, []
    snapshot = imported_baseline.lookup(cfg, path)
    split = None if snapshot is None else _split_snapshot(path, findings, cfg, snapshot, text)
    if split is not None:
        return split
    before = committed_text(path)
    if before is None:
        return findings, []
    return _halves(findings, scan_all(str(path), before, cfg), cfg)


def split_fallback(path: Path, rows: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Unscannable rows of an unchanged imported file stay advice, because the agent never wrote that file."""
    if not rows or baseline_mode(cfg) == "none":
        return rows, []
    snapshot = imported_baseline.lookup(cfg, path)
    if snapshot is None or imported_baseline.file_digest(path) != snapshot.digest:
        return rows, []
    return [], rows if baseline_mode(cfg) == "report" else []


def split_against(texts: Texts, path: str, findings: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Pool every previous text because a merge resolution may take a line from any parent."""
    present = [text for text in texts if text is not None]
    if not findings or not present or baseline_mode(cfg) == "none":
        return findings, []
    pooled = [row for text in present for row in scan_all(path, text, cfg)]
    return _halves(findings, pooled, cfg)


def strip_committed(path: Path, findings: list[dict], cfg: dict, text: str | None = None) -> list[dict]:
    return split_committed(path, findings, cfg, text)[0]


def strip_against(texts: Texts, path: str, findings: list[dict], cfg: dict) -> list[dict]:
    return split_against(texts, path, findings, cfg)[0]
