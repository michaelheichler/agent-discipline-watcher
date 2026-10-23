"""Resolves git rm pathspecs, because git's * crosses / and a folder name takes every entry below it, so only the index knows what goes."""
from __future__ import annotations

import glob
import subprocess
from collections.abc import Sequence
from pathlib import Path

GIT_TIMEOUT_SECONDS = 2
LITERAL_MAGIC = ":(literal)"


def removed_paths(pathspecs: Sequence[str], directory: Path) -> list[str] | None:
    """None when git cannot answer, because an unread index may hold tests."""
    expanded = [match for pattern in pathspecs for match in _shell_matches(pattern, directory)]
    listed = _git_list(["ls-files", "-z", "--", *pathspecs, *(LITERAL_MAGIC + match for match in expanded)], directory)
    return None if listed is None else sorted({*expanded, *listed})


def tree_paths(tree: str, pathspecs: Sequence[str], directory: Path) -> list[str] | None:
    """Read from the named tree, because restore --source and checkout TREE -- copy files the index may not hold."""
    if tree.startswith("-"):
        return None
    return _git_list(["ls-tree", "-r", "-z", "--name-only", tree, "--", *pathspecs], directory)


def _git_list(arguments: list[str], directory: Path) -> list[str] | None:
    try:
        listed = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True, text=True, errors="surrogateescape", timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [path for path in listed.stdout.split("\0") if path] if listed.returncode == 0 else None


def _shell_matches(pattern: str, directory: Path) -> list[str]:
    """Widest shell reading, because an unquoted glob reaches git as worktree paths and a matched folder goes whole."""
    return glob.glob(pattern, root_dir=directory, recursive=True, include_hidden=True)
