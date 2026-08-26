"""Resolves which paths a shell segment actually writes, because treating every path token in a mutating segment as a target blocks reads the agent is entitled to."""
from __future__ import annotations

from lib.shell_parse import (
    _bare, _basename, _command_word_index, _expand_home, _is_file_target, _write_paths,
)

DESTINATION_LAST_ARG_VERBS = frozenset({"cp", "mv", "ln", "sed"})
DESTINATION_ALL_ARGS_VERBS = frozenset({"rm", "unlink", "shred", "truncate", "chmod", "chown"})
TARGET_DIR_VERBS = frozenset({"cp", "mv", "ln"})
TARGET_DIR_FLAGS = frozenset({"-t", "--target-directory"})


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
    for position, token in enumerate(args):
        bare = _bare(token)
        if bare.startswith("--target-directory="):
            return bare.partition("=")[2]
        if bare in TARGET_DIR_FLAGS and position + 1 < len(args):
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
