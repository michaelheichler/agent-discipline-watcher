"""Hold an edit responsible for what it changed, not for debt the committed file already carried."""
from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

try:
    from .scanner import scan_all
except ImportError:
    from scanner import scan_all


BASELINE_MODES = ("git", "none")
GIT_TIMEOUT_SECONDS = 10


def baseline_mode(cfg: dict) -> str:
    """Resolve the mode, defaulting to git so that a legacy file never blocks an unrelated edit."""
    mode = cfg.get("baseline")
    return mode if mode in BASELINE_MODES else "git"


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


def finding_key(finding: dict) -> tuple[str, str, str]:
    """Identify a finding without its line number, so that an edit shifting a file does not resurface old debt."""
    return (
        str(finding.get("family", "")),
        str(finding.get("rule", "")),
        str(finding.get("snippet", "")).strip(),
    )


def subtract(findings: list[dict], baseline: list[dict]) -> list[dict]:
    """Drop what the baseline already had, counting copies so that a repeated finding still reports its extras."""
    budget = Counter(finding_key(row) for row in baseline)
    kept = []
    for row in findings:
        key = finding_key(row)
        if budget[key]:
            budget[key] -= 1
            continue
        kept.append(row)
    return kept


def strip_committed(path: Path, findings: list[dict], cfg: dict) -> list[dict]:
    """Return the findings this edit owns, leaving whatever HEAD already carried to the file's own history."""
    if not findings or baseline_mode(cfg) == "none":
        return findings
    text = committed_text(path)
    if text is None:
        return findings
    return subtract(findings, scan_all(str(path), text, cfg))


def strip_against(text: str | None, path: str, findings: list[dict], cfg: dict) -> list[dict]:
    """Subtract an already-resolved baseline text, for callers that read the old version themselves."""
    if not findings or text is None or baseline_mode(cfg) == "none":
        return findings
    return subtract(findings, scan_all(path, text, cfg))
