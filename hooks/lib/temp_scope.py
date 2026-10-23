"""Scans skip temp files, because scratch is not project output."""
from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from lib.shell_syntax import _bare, _basename, _command_word_index, _is_literal_token, _segments, _tokens

FIXED_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
DIRECTORY_VERBS = frozenset({"cd", "pushd", "popd"})
LEADING_CD_SEPARATORS = frozenset({"&&", ";"})
EXPANDING_RE = re.compile(r"[*?\[{\\$`]")
MAX_DIRECTORY_CANDIDATES = 16
Directories = tuple[str, ...] | None
Resolve = Callable[[str], "str | None"]


class _Walk(NamedTuple):
    cwd: Path | None
    resolve: Resolve | None


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


def leading_directory(command: str) -> str | None:
    """Because only a lone cd DIR && or cd DIR ; at the start can put every relative target under DIR, any other directory change yields None."""
    lines = command.splitlines()
    tokens = _tokens(lines[0]) if lines else []
    if len(tokens) < 3 or tokens[0] != "cd" or tokens[2] not in LEADING_CD_SEPARATORS or not _plain_path(tokens[1]):
        return None
    changes = [segment for line in lines for segment in _segments(line) if _changes_directory(segment)]
    return _bare(tokens[1]) if len(changes) == 1 else None


def trusted_directory(command: str, cwd: str | os.PathLike[str] | None) -> str | None:
    """Because a failed cd leaves the shell in the session cwd, only a cd joined by && into a searchable directory is sure to move it."""
    directory = leading_directory(command)
    if directory is None or _tokens(command.splitlines()[0])[2] != "&&":
        return None
    absolute = _absolute(directory, cwd)
    return directory if absolute.is_dir() and os.access(absolute, os.X_OK) else None


def command_targets(path: str, command: str, cwd: str | os.PathLike[str] | None) -> list[str]:
    """Because the cd may fail, an untrusted leading cd leaves a relative target in either directory."""
    directory = leading_directory(command)
    if directory is None or path.startswith("~") or Path(path).is_absolute():
        return [path]
    joined = os.path.join(directory, path)
    return [joined] if trusted_directory(command, cwd) else [joined, path]


def scratch_target(path: str, command: str, cwd: str | os.PathLike[str] | None) -> bool:
    if not _plain_path(path) or path.startswith("~"):
        return False
    if Path(path).is_absolute():
        return outside_project_temp(path, cwd)
    directory = trusted_directory(command, cwd)
    return directory is not None and outside_project_temp(_absolute(directory, cwd) / path, cwd)


def segment_directories(segments: list[list[str]], start: Directories, resolve: Resolve | None = None) -> list[Directories]:
    """Every folder each segment may run in, because a failed cd leaves the shell where it was."""
    return _walked_directories(segments, start, _Walk(None, resolve))


def landing_directories(segments: list[list[str]], cwd: str | os.PathLike[str] | None, resolve: Resolve | None = None) -> list[Directories]:
    """Pruned to the folder a cd reaches when it exists, because a cd into an existing folder does not fail."""
    return _walked_directories(segments, (".",), _Walk(Path(cwd or ".").absolute(), resolve))


def joined_paths(paths: list[str], folders: Directories) -> list[str]:
    """Relative paths dropped under an unknown folder, because naming them against the session cwd points at the wrong file."""
    anchored = [path for path in paths if path.startswith("~") or os.path.isabs(path)]
    relative = [path for path in paths if path not in anchored]
    return anchored + [os.path.normpath(os.path.join(folder, path)) for path in relative for folder in folders or ()]


def _walked_directories(segments: list[list[str]], start: Directories, walk: _Walk) -> list[Directories]:
    current = start
    found: list[Directories] = []
    for segment in segments:
        found.append(current)
        current = _after_directory_change(segment, current, walk)
    return found


def _after_directory_change(segment: list[str], current: Directories, walk: _Walk) -> Directories:
    index = _command_word_index(segment)
    if index < len(segment) and _bare(segment[index]) == "builtin":
        return None
    if current is None or not _changes_directory(segment):
        return current
    target = _cd_target(segment[index:], walk.resolve)
    if target is None:
        return None
    moved = {os.path.normpath(os.path.join(folder, target)) for folder in current}
    kept = set() if walk.cwd is not None and all(_searchable(walk.cwd / folder) for folder in moved) else set(current)
    reached = tuple(sorted(kept | moved))
    return reached if len(reached) <= MAX_DIRECTORY_CANDIDATES else None


def _searchable(folder: Path) -> bool:
    return folder.is_dir() and os.access(folder, os.X_OK)


def _cd_target(words: list[str], resolve: Resolve | None) -> str | None:
    """None for pushd, popd, cd -, or a computed folder, because only the shell knows where those land."""
    operands = [word for word in words[1:] if not _bare(word).startswith("-")]
    if _basename(words[0]) != "cd" or len(operands) > 1 or "-" in map(_bare, words[1:]):
        return None
    if not operands:
        return os.path.expanduser("~")
    folder = resolve(operands[0]) if resolve is not None else (_bare(operands[0]) if _plain_path(operands[0]) else None)
    return None if folder is None else os.path.expanduser(folder)


def _plain_path(token: str) -> bool:
    bare = _bare(token)
    return bool(bare) and not bare.startswith("-") and _is_literal_token(token) and not EXPANDING_RE.search(bare)


def _changes_directory(segment: list[str]) -> bool:
    index = _command_word_index(segment)
    return index < len(segment) and _basename(segment[index]) in DIRECTORY_VERBS
