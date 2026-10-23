"""Because a file under a dot-directory holds tool state rather than project output, no model review reads it."""
from __future__ import annotations

import os
from pathlib import Path

REVIEWED_DOT_DIRECTORIES = frozenset({".github"})
REPOSITORY_MARKER = ".git"


def is_project_file(path: str | Path, project: str | Path | None = None) -> bool:
    target = _real(path)
    root = _project_root(target, project)
    parts = target.relative_to(root).parts if root is not None and target.is_relative_to(root) else target.parts
    return not any(_hidden(part) for part in parts[:-1])


def _project_root(target: Path, project: str | Path | None) -> Path | None:
    if not project:
        return _repository(target.parent)
    start = _real(project)
    return _repository(start) or start


def _repository(start: Path) -> Path | None:
    return next((directory for directory in (start, *start.parents) if (directory / REPOSITORY_MARKER).exists()), None)


def _hidden(part: str) -> bool:
    return part.startswith(".") and part not in REVIEWED_DOT_DIRECTORIES


def _real(path: str | Path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(path)))
