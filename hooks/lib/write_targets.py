"""Resolves which paths a shell segment actually writes, because treating every path token in a mutating segment as a target blocks reads the agent is entitled to."""
from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import NamedTuple

from lib.shell_parse import (
    _bare, _basename, _command_word_index, _expand_home, _is_file_target, _skip_leading_redirect, _write_paths,
)

DESTINATION_LAST_ARG_VERBS = frozenset({"cp", "mv", "ln", "sed"})
DESTINATION_ALL_ARGS_VERBS = frozenset({"rm", "unlink", "shred", "truncate", "chmod", "chown"})
TARGET_DIR_VERBS = frozenset({"cp", "mv", "ln"})
TARGET_DIR_FLAGS = frozenset({"-t", "--target-directory"})
COPY_VERBS = frozenset({"cp", "mv", "ln", "install", "rsync"})
GIT_PATH_COMMANDS = frozenset({"checkout", "restore", "rm"})
GIT_VALUE_FLAGS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
GIT_BASE_FLAGS = frozenset({"-C", "--work-tree"})
WORK_TREE_PREFIX = "--work-tree="
GLOB_CHARS = frozenset("*?[")
GIT_DRY_APPLY_FLAGS =frozenset({"--check", "--stat", "--numstat", "--summary"})
UNZIP_READ_FLAGS = frozenset({"-l", "-t", "-p", "-v", "-Z", "-z"})
TAR_EXTRACT_FLAGS = frozenset({"--extract", "--get"})


class GatedTargets(NamedTuple):
    """Unresolved, because a patch or archive names no paths."""

    paths: tuple[str, ...]
    unresolved: bool


NO_TARGETS = GatedTargets((), False)
UNRESOLVED = GatedTargets((), True)


def mutation_targets(segment: list[str]) -> list[str]:
    """Because a copy's source argument is not its destination, a protected path used as input must not block a read."""
    targets = [_expand_home(path) for path in _write_paths(segment)]
    index = _command_word_index(segment)
    if index >= len(segment):
        return [path for path in targets if _is_file_target(path)]
    verb = _basename(segment[index])
    args = segment[index + 1:]
    target_dir = _target_directory(args) if verb in TARGET_DIR_VERBS else None
    if target_dir is not None:
        targets.append(_expand_home(target_dir))
    targets.extend(_verb_targets(verb, _drop_target_dir(args), target_dir))
    return [path for path in targets if _is_file_target(path)]


def _verb_targets(verb: str, args: list[str], target_dir: str | None) -> list[str]:
    """Kept apart from the redirect targets, because an unknown verb must contribute nothing rather than every path it mentions."""
    raw_args = [token for token in args if not _bare(token).startswith("-")]
    if verb == "dd":
        return [_expand_home(_bare(token)) for token in raw_args if _bare(token).startswith("of=")]
    if verb in DESTINATION_LAST_ARG_VERBS and raw_args and target_dir is None:
        return [_expand_home(_bare(raw_args[-1]))]
    if verb in DESTINATION_ALL_ARGS_VERBS:
        return [_expand_home(_bare(token)) for token in raw_args]
    return []


def _target_directory(args: list[str]) -> str | None:
    """Because -t/--target-directory names the real destination for GNU cp, mv, and ln, the last positional argument must defer to it."""
    return _option_value(args, TARGET_DIR_FLAGS, "--target-directory=")


def _option_value(args: list[str], flags: frozenset[str], joined_prefix: str) -> str | None:
    for position, token in enumerate(args):
        bare = _bare(token)
        if joined_prefix and bare.startswith(joined_prefix):
            return bare[len(joined_prefix):]
        if bare in flags and position + 1 < len(args):
            return _bare(args[position + 1])
    return None


def _drop_target_dir(args: list[str]) -> list[str]:
    kept = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        bare = _bare(token)
        if bare.startswith("--target-directory="):
            continue
        if bare in TARGET_DIR_FLAGS:
            skip_next = True
            continue
        kept.append(token)
    return kept


def gated_test_targets(segment: list[str]) -> GatedTargets:
    """Kept apart, because only the test gate judges these verbs."""
    index = _command_word_index(segment)
    if index >= len(segment):
        return NO_TARGETS
    verb = _basename(segment[index])
    args = _without_redirects(segment[index + 1:])
    if verb in COPY_VERBS:
        return GatedTargets(tuple(_expand_home(path) for path in _copy_targets(verb, args)), False)
    if verb == "git":
        return _git_targets([_bare(token) for token in args])
    if verb == "patch":
        return UNRESOLVED
    if verb in {"tar", "unzip"}:
        return _archive_targets(verb, args)
    return NO_TARGETS


def _without_redirects(args: list[str]) -> list[str]:
    kept = []
    position = 0
    while position < len(args):
        skipped = _skip_leading_redirect(args, position)
        if skipped is None:
            kept.append(args[position])
        position = position + 1 if skipped is None else skipped
    return kept


def _positional(args: list[str]) -> list[str]:
    return [_bare(token) for token in args if not _bare(token).startswith("-")]


def _copy_targets(verb: str, args: list[str]) -> list[str]:
    """Join each source, because a test name survives a copy."""
    target_dir = _target_directory(args) if verb != "rsync" else None
    sources = _positional(_drop_target_dir(args))
    if target_dir is None:
        if len(sources) < 2:
            return sources
        target_dir, sources = sources[-1], sources[:-1]
    joined = [os.path.join(target_dir, PurePosixPath(source).name) for source in sources]
    return [target_dir, *joined, *(sources if verb == "mv" else [])]


def _git_base(words: list[str]) -> tuple[str, int]:
    """Join -C and --work-tree, because pathspecs resolve below them."""
    position = 0
    base = ""
    while position < len(words) and words[position].startswith("-"):
        flag = words[position]
        base = os.path.join(base, _base_value(flag, words[position + 1:position + 2]))
        position += 2 if flag in GIT_VALUE_FLAGS else 1
    return base, position


def _base_value(flag: str, following: list[str]) -> str:
    if flag.startswith(WORK_TREE_PREFIX):
        return flag[len(WORK_TREE_PREFIX):]
    return following[0] if flag in GIT_BASE_FLAGS and following else ""


def _git_targets(words: list[str]) -> GatedTargets:
    base, position = _git_base(words)
    command, rest = (words[position], words[position + 1:]) if position < len(words) else ("", [])
    if command in GIT_PATH_COMMANDS:
        paths = rest[rest.index("--") + 1:] if "--" in rest else _positional(rest)
        if any(_is_directory_pathspec(path) for path in paths):
            return UNRESOLVED
        return GatedTargets(tuple(_expand_home(os.path.join(base, path)) for path in paths), False)
    dry_apply = bool(GIT_DRY_APPLY_FLAGS.intersection(rest)) and "--apply" not in rest
    if (command == "apply" and not dry_apply) or (command == "stash" and rest[:1] in (["pop"], ["apply"])):
        return UNRESOLVED
    return NO_TARGETS


def _is_directory_pathspec(path: str) -> bool:
    """A dir or glob, because it may hold tests no name shows."""
    return (
        path in {"", ".", ".."} or path.endswith(("/", "/.", "/..")) or path.startswith(":")
        or any(char in path for char in GLOB_CHARS)
    )


def _archive_targets(verb: str, args: list[str]) -> GatedTargets:
    """Unresolved, because an archive member may be a test."""
    words = [_bare(token) for token in args]
    if verb == "tar":
        return UNRESOLVED if _tar_extracts(words) else NO_TARGETS
    return NO_TARGETS if UNZIP_READ_FLAGS.intersection(words) else UNRESOLVED


def _tar_extracts(words: list[str]) -> bool:
    if words and not words[0].startswith("-") and "x" in words[0]:
        return True
    return any(
        word in TAR_EXTRACT_FLAGS or (word.startswith("-") and not word.startswith("--") and "x" in word)
        for word in words
    )
