"""Hold an edit responsible for what it changed, not for debt the committed file already carried."""
from __future__ import annotations

import difflib
import subprocess
from collections import Counter
from pathlib import Path

try:
    from .scanner import scan_all
except ImportError:
    from scanner import scan_all


BASELINE_MODES = ("git", "report", "none")
DEFAULT_BASELINE_MODE = "report"
GIT_TIMEOUT_SECONDS = 10


def baseline_mode(cfg: dict) -> str:
    """Resolve the mode, defaulting to report so inherited debt is named instead of vanishing without a trace."""
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
    """Return the file as HEAD holds it, or None when no committed version exists to compare against."""
    located = _repo_relative(path)
    if located is None:
        return None
    directory, relative = located
    return _git(["show", "HEAD:" + relative], directory)


def changed_lines(before: str, after: str) -> set[int]:
    """Return post-edit line numbers covered by non-equal diff hunks."""
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
    """Identify a finding by family and rule alone, ignoring the text it points at."""
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
    exact = Counter(finding_key(row) for row in baseline)
    survivors = _consume(findings, exact, finding_key)
    if not survivors:
        return []
    loose: Counter = Counter()
    for key, remaining in exact.items():
        loose[key[:2]] += remaining
    return _consume(survivors, loose, rule_key)


def partition(findings: list[dict], baseline: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into what the edit owns and what it inherited, so a caller can surface the second without blocking on it."""
    owned = subtract(findings, baseline)
    kept = {id(row) for row in owned}
    return owned, [row for row in findings if id(row) not in kept]


def _halves(findings: list[dict], baseline: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Withhold the inherited half outside report mode, because git mode promises silence about committed debt."""
    owned, inherited = partition(findings, baseline)
    return owned, inherited if baseline_mode(cfg) == "report" else []


def split_committed(path: Path, findings: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Return the owned and inherited halves against HEAD, so an edit answers for its own debt and hears about the rest."""
    if not findings or baseline_mode(cfg) == "none":
        return findings, []
    text = committed_text(path)
    if text is None:
        return findings, []
    return _halves(findings, scan_all(str(path), text, cfg), cfg)


def split_against(text: str | None, path: str, findings: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Split against an already-resolved baseline text, for callers that read the old version themselves."""
    if not findings or text is None or baseline_mode(cfg) == "none":
        return findings, []
    return _halves(findings, scan_all(path, text, cfg), cfg)


def strip_committed(path: Path, findings: list[dict], cfg: dict) -> list[dict]:
    """Return the owned half alone, kept for callers that have no use for the inherited one."""
    return split_committed(path, findings, cfg)[0]


def strip_against(text: str | None, path: str, findings: list[dict], cfg: dict) -> list[dict]:
    """Return the owned half alone, kept for callers that have no use for the inherited one."""
    return split_against(text, path, findings, cfg)[0]
