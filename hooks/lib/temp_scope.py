"""Scans skip temp files, because scratch is not project output."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from lib.shell_syntax import _bare, _basename, _command_word_index, _is_literal_token, _segments, _tokens
from lib.write_targets import _drop_target_dir, _expand_home, _target_directory

FIXED_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
COPY_VERBS = frozenset({"cp", "mv", "install", "rsync"})
DIRECTORY_VERBS = frozenset({"cd", "pushd", "popd"})
LEADING_CD_SEPARATORS = frozenset({"&&", ";"})
EXPANDING_RE = re.compile(r"[*?\[{\\$`]")


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
    """Because only a lone cd DIR && or cd DIR ; at the start puts every relative target under DIR, any other directory change yields None."""
    lines = command.splitlines()
    tokens = _tokens(lines[0]) if lines else []
    if len(tokens) < 3 or tokens[0] != "cd" or tokens[2] not in LEADING_CD_SEPARATORS or not _plain_path(tokens[1]):
        return None
    changes = [segment for line in lines for segment in _segments(line) if _changes_directory(segment)]
    return _bare(tokens[1]) if len(changes) == 1 else None


def command_target(path: str, directory: str | None) -> str:
    """Because the shell resolves a relative target under the leading cd, the session cwd would name the wrong file."""
    if directory is None or path.startswith("~") or Path(path).is_absolute():
        return path
    return os.path.join(directory, path)


def scratch_target(path: str, command: str, cwd: str | os.PathLike[str] | None) -> bool:
    """Because a failed cd leaves a relative target in the session cwd, it counts only under a leading cd directory that exists."""
    if not _plain_path(path) or path.startswith("~"):
        return False
    if Path(path).is_absolute():
        return outside_project_temp(path, cwd)
    directory = leading_directory(command)
    if directory is None or not _absolute(directory, cwd).is_dir():
        return False
    return outside_project_temp(_absolute(directory, cwd) / path, cwd)


def _plain_path(token: str) -> bool:
    bare = _bare(token)
    return bool(bare) and not bare.startswith("-") and _is_literal_token(token) and not EXPANDING_RE.search(bare)


def _changes_directory(segment: list[str]) -> bool:
    index = _command_word_index(segment)
    return index < len(segment) and _basename(segment[index]) in DIRECTORY_VERBS


def temp_copy_destinations(command: str, cwd: str | os.PathLike[str] | None) -> list[str]:
    """Scanned, because a copy must not launder temp text."""
    found: list[str] = []
    for segment in _segments(command):
        index = _command_word_index(segment)
        if index < len(segment) and _basename(segment[index]) in COPY_VERBS:
            found.extend(_segment_destinations(segment[index + 1:], cwd))
    return found


def _segment_destinations(args: list[str], cwd: str | os.PathLike[str] | None) -> list[str]:
    target_dir = _target_directory(args)
    paths = [_expand_home(_bare(token)) for token in _drop_target_dir(args) if not _bare(token).startswith("-")]
    if target_dir is not None:
        sources, target = paths, _expand_home(target_dir)
    elif len(paths) >= 2:
        sources, target = paths[:-1], paths[-1]
    else:
        return []
    temp_sources = [source for source in sources if outside_project_temp(source, cwd)]
    return [landed for source in temp_sources for landed in _landed_files(source, target, cwd)]


def _landed_files(source: str, target: str, cwd: str | os.PathLike[str] | None) -> list[str]:
    destination = _absolute(target, cwd)
    named = destination / Path(source.rstrip("/")).name
    if named.exists():
        destination = named
    if not destination.is_dir():
        return [str(destination)]
    if _within(Path(cwd or ".").absolute(), (destination,)):
        return []
    return [str(path) for path in sorted(destination.rglob("*")) if path.is_file()]
