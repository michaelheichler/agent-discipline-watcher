"""A copy from temp lands only what its source held, because the destination may already carry files nobody copied."""
from __future__ import annotations

import fnmatch
import glob
import os
from pathlib import Path
from typing import NamedTuple

from lib import session_state
from lib.shell_syntax import _bare, _basename, _command_word_index, _segments
from lib.temp_scope import _absolute, _within, outside_project_temp
from lib.write_targets import _drop_target_dir, _expand_home, _target_directory

COPY_VERBS = frozenset({"cp", "mv", "install", "rsync"})
AUTHORED_KEY = "authored_temp"
MAX_AUTHORED = 256
GLOB_CHARS = frozenset("*?[")
Cwd = str | os.PathLike[str] | None


class Landing(NamedTuple):
    source: str
    destination: str


class _Copy(NamedTuple):
    verb: str
    source: str
    destination: Path
    cwd: Cwd
    authored: frozenset[str] | None


def source_key(path: str | os.PathLike[str], cwd: Cwd = None) -> str:
    return os.path.realpath(_absolute(path, cwd))


def note_authored_temp(session_id: str, paths: list[str], cwd: Cwd, root: Cwd) -> None:
    """Remembered per session, because only a temp file the agent wrote can make its copy the agent's own."""
    keys = list(dict.fromkeys(source_key(path, cwd) for path in paths))
    if not session_id or not keys:
        return

    def mutate(state: dict) -> dict:
        stored = state.get(AUTHORED_KEY)
        known = [value for value in stored if isinstance(value, str)] if isinstance(stored, list) else []
        merged = [value for value in known if value not in keys] + keys
        return {**state, AUTHORED_KEY: merged[-MAX_AUTHORED:]}

    session_state.update_state(session_id, mutate, root)


def authored_temp(session_id: str, root: Cwd) -> frozenset[str]:
    if not session_id:
        return frozenset()
    stored = session_state.read_state(session_id, root).get(AUTHORED_KEY)
    return frozenset(value for value in stored if isinstance(value, str)) if isinstance(stored, list) else frozenset()


def temp_copy_destinations(command: str, cwd: Cwd) -> list[str]:
    """Kept whole, because a caller without provenance cannot tell an import from a write and must fail closed."""
    return list(dict.fromkeys(landing.destination for landing in _landings(command, cwd, None)))


def copy_landings(command: str, cwd: Cwd, authored: frozenset[str]) -> tuple[list[str], list[str]]:
    owned: dict[str, None] = {}
    imported: dict[str, None] = {}
    for landing in _landings(command, cwd, authored):
        (owned if landing.source in authored else imported)[landing.destination] = None
    return list(owned), [path for path in imported if path not in owned]


def _landings(command: str, cwd: Cwd, authored: frozenset[str] | None) -> list[Landing]:
    found: list[Landing] = []
    for segment in _segments(command):
        index = _command_word_index(segment)
        if index < len(segment) and _basename(segment[index]) in COPY_VERBS:
            verb = _basename(segment[index])
            found.extend(_segment_landings(verb, segment[index + 1:], cwd, authored))
    return found


def _segment_landings(verb: str, args: list[str], cwd: Cwd, authored: frozenset[str] | None) -> list[Landing]:
    target_dir = _target_directory(args)
    paths = [_expand_home(_bare(token)) for token in _drop_target_dir(args) if not _bare(token).startswith("-")]
    if target_dir is not None:
        sources, target = paths, _expand_home(target_dir)
    elif len(paths) >= 2:
        sources, target = paths[:-1], paths[-1]
    else:
        return []
    destination = _absolute(target, cwd)
    return [
        landing
        for source in sources if outside_project_temp(source, cwd)
        for landing in _source_landings(_Copy(verb, source, destination, cwd, authored))
    ]


def _source_landings(copy: _Copy) -> list[Landing]:
    if any(char in copy.source for char in GLOB_CHARS):
        matches = sorted(glob.glob(str(_absolute(copy.source, copy.cwd))))
        if matches:
            return [landing for match in matches for landing in _tree_landings(Path(match), copy.destination, False)]
        return _moved_glob_landings(copy)
    source = _absolute(copy.source, copy.cwd)
    if source.exists():
        contents = copy.source.endswith("/.") or (copy.verb == "rsync" and copy.source.endswith("/"))
        return _tree_landings(source, copy.destination, contents)
    return _moved_landings(copy, source) if copy.verb == "mv" else []


def _tree_landings(source: Path, destination: Path, contents: bool) -> list[Landing]:
    if source.is_file():
        landed = destination / source.name if destination.is_dir() else destination
        return [Landing(source_key(source), str(landed))] if landed.is_file() else []
    if not source.is_dir():
        return []
    named = destination / source.name
    root = destination if contents or not named.is_dir() else named
    pairs = ((item, root / item.relative_to(source)) for item in sorted(source.rglob("*")) if item.is_file())
    return [Landing(source_key(item), str(landed)) for item, landed in pairs if landed.is_file()]


def _moved_landings(copy: _Copy, source: Path) -> list[Landing]:
    """Only authored files count here, because a failed move would otherwise sweep the whole destination."""
    named = copy.destination / source.name
    root = named if named.exists() else copy.destination
    if _within(Path(copy.cwd or ".").absolute(), (root,)):
        return []
    if root.is_file():
        landings = [Landing(source_key(source), str(root))]
    else:
        base = source_key(source)
        landings = [
            Landing(os.path.join(base, str(item.relative_to(root))), str(item))
            for item in sorted(root.rglob("*")) if item.is_file()
        ]
    return [landing for landing in landings if copy.authored is None or landing.source in copy.authored]


def _moved_glob_landings(copy: _Copy) -> list[Landing]:
    if not copy.authored or not copy.destination.is_dir():
        return []
    pattern = source_key(copy.source, copy.cwd)
    return [
        Landing(key, str(copy.destination / Path(key).name))
        for key in sorted(copy.authored)
        if fnmatch.fnmatchcase(key, pattern) and (copy.destination / Path(key).name).is_file()
    ]
