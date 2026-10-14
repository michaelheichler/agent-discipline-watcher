"""Scans skip temp files, because scratch is not project output."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

FIXED_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


def _absolute(path: str | os.PathLike[str], cwd: str | os.PathLike[str] | None) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else Path(cwd or ".").absolute() / candidate


def _forms(path: Path) -> tuple[Path, ...]:
    """Both forms, because a symlink must not hide either side."""
    lexical = Path(os.path.normpath(path))
    try:
        return lexical, lexical.resolve()
    except (OSError, RuntimeError, ValueError):
        return (lexical,)


def temp_roots() -> tuple[Path, ...]:
    raw = (*FIXED_TEMP_ROOTS, tempfile.gettempdir(), os.environ.get("TMPDIR") or "")
    return tuple({form for item in raw if item for form in _forms(Path(item))})


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def outside_project_temp(path: str | os.PathLike[str], cwd: str | os.PathLike[str] | None) -> bool:
    """Uses cwd, because pytest projects live under temp."""
    if not cwd or not Path(cwd).is_absolute():
        return False
    forms = _forms(_absolute(path, cwd))
    if not all(_within(form, temp_roots()) for form in forms):
        return False
    return not any(_within(form, _forms(Path(cwd))) for form in forms)