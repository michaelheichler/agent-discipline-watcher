"""Because readers and identity keys differ, keep lexical paths separate from canonical paths."""
from __future__ import annotations

import os
from pathlib import Path


def real_path(path: str | os.PathLike[str]) -> Path:
    """Because imported identities allow missing users, resolve links but keep unknown homes literal."""
    return Path(os.path.realpath(os.path.expanduser(os.fspath(path))))


def lexical_absolute(path: str | os.PathLike[str]) -> Path:
    """Because no-follow reads reject links, expand homes and dots without resolving symlinks."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def anchored(path: str | os.PathLike[str], cwd: Path) -> Path:
    """Keep lexical targets because lstat must inspect links before following them."""
    candidate = Path(os.path.expanduser(os.fspath(path)))
    return candidate if candidate.is_absolute() else cwd / candidate


def anchored_identity(path: str | os.PathLike[str], cwd: Path) -> Path:
    """Share canonical keys because batch correlation must match the file scanner."""
    # Because home expansion is done, only resolve links and dots here.
    return Path(os.path.realpath(anchored(path, cwd)))
