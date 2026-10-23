"""Collects what a shell command may change for the test gate, because a cd or a git glob moves a write away from its spelling."""
from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

from lib.git_globs import removed_paths, tree_paths
from lib.shell_expansion import Tree
from lib.shell_parse import command_expansions, line_segments
from lib.temp_scope import Directories, _changes_directory, joined_paths, segment_directories
from lib.test_units import language_of
from lib.tests_policy import is_test_path
from lib.write_targets import GatedTargets, GitLookup, gated_test_targets, mutation_targets

OUTER_START: tuple[str, ...] = (".",)
# Because the gate reads each judged file, a bigger removed folder stays closed.
MAX_JUDGED_FILES = 2_000


class Scope(NamedTuple):
    """Grouped, because a payload inherits every folder the outer command may reach but none of its index lookups."""

    cwd: Path
    directories: Directories
    outer: bool


def reachable_directories(command: str, cwd: Path) -> Directories:
    """Because a sh -c payload starts wherever its segment did, it may start in any folder the command reaches."""
    found = segment_directories(line_segments(command), OUTER_START, command_expansions(command, cwd).path)
    if None in found:
        return None
    return tuple(sorted({folder for folders in found if folders for folder in folders}))


def gated_paths(command: str, scope: Scope) -> tuple[list[str], list[str]]:
    """Each path under every folder its segment may run in, because a failed or later cd moves it."""
    expansions = command_expansions(command, scope.cwd)
    segments = line_segments(command)
    paths: list[str] = []
    unresolved: list[str] = []
    for position, (segment, folders) in enumerate(zip(segments, segment_directories(segments, scope.directories, expansions.path))):
        gated = gated_test_targets(segment, expansions)
        lookups = scope.outer and all(map(_changes_directory, segments[:position]))
        named = _in_folders([*gated.paths, *mutation_targets(segment, expansions)], folders)
        looked_up = _lookup_paths(gated._replace(indexable=gated.indexable and lookups), folders, scope.cwd)
        inside = _tree_tests(expansions.tree(segment))
        paths.extend([*(named or []), *(looked_up or []), *(inside or [])])
        if gated.unresolved or named is None or looked_up is None or inside is None:
            unresolved.append(" ".join(segment))
    return paths, unresolved


def _tree_tests(tree: Tree | None) -> list[str] | None:
    """Test names and inline-test languages only, because no other file in a removed folder can hold a guarded test."""
    candidates = [] if tree is None else [path for path in tree.files if is_test_path(path) or language_of(path)]
    return candidates if len(candidates) <= MAX_JUDGED_FILES else None


def _in_folders(paths: list[str], folders: Directories) -> list[str] | None:
    """None for a relative path under an unknown folder, because only the shell knows where it lands."""
    joined = joined_paths(paths, folders)
    return None if folders is None and len(joined) < len(paths) else joined


def _lookup_paths(gated: GatedTargets, folders: Directories, cwd: Path) -> list[str] | None:
    """None when git may change more than its words name, because a folder or a glob can hold tests."""
    lookup = gated.lookup
    if lookup is None:
        return []
    if folders is None or not gated.indexable:
        literal = [os.path.join(lookup.base, path) for path in lookup.pathspecs]
        named_files = folders is not None and all(_names_a_file(path, folders, cwd) for path in literal)
        return [] if not lookup.strict or named_files else None
    found: list[str] = []
    for folder in folders:
        listed = _listed(lookup, cwd / folder / lookup.base)
        if listed is None:
            return None if lookup.strict else found
        found.extend(os.path.normpath(os.path.join(folder, lookup.base, path)) for path in listed)
    return found


def _listed(lookup: GitLookup, directory: Path) -> list[str] | None:
    if lookup.tree is None:
        return removed_paths(lookup.pathspecs, directory)
    return tree_paths(lookup.tree, lookup.pathspecs, directory)


def _names_a_file(path: str, folders: tuple[str, ...], cwd: Path) -> bool:
    """Because an earlier command can change the index, a word read without git must name a file, not a folder."""
    candidates = [cwd / folder / path for folder in folders]
    return any(map(Path.is_file, candidates)) and not any(map(Path.is_dir, candidates))
