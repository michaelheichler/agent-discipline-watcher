"""Guarded because an agent must not widen its own gate."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .shell_syntax import (
    DYNAMIC_RE, _basename, _command_word_index, _payload_command_index, _segments, _words,
    interpreter_invocation,
)

CLI_NAME = "adw-config"
MODULE_NAMES = frozenset({"lib.adw_config", "adw_config", "adw_config.py"})
SUBCOMMANDS = frozenset({"tests", "family"})
READ_ONLY_ARGS = ([], ["status"])
COPY_VERBS = frozenset({"ln", "cp", "install", "rsync"})
REPARSE_VERBS = frozenset({"eval", "xargs"})


def _plain(word: str) -> str:
    return word.replace("\\", "").replace("'", "").replace('"', "")


def _located(word: str, cwd: Path) -> Path | None:
    if "/" not in word:
        found = shutil.which(word)
        return Path(found) if found else None
    target = Path(os.path.expanduser(word))
    return target if target.is_absolute() else cwd / target


def _resolved_name(word: str, cwd: Path) -> str | None:
    """Resolved because a renamed link still runs the CLI."""
    try:
        target = _located(word, cwd)
        return None if target is None else Path(os.path.realpath(target)).name
    except (OSError, ValueError):
        return None


def _is_cli(word: str, cwd: Path) -> bool:
    plain = _plain(word)
    if _basename(plain) == CLI_NAME:
        return True
    if not plain or DYNAMIC_RE.search(plain):
        return False
    return _resolved_name(plain, cwd) == CLI_NAME


def _runs_python(segment: list[str]) -> bool:
    index = _payload_command_index(segment)
    return index < len(segment) and _basename(segment[index]).startswith("python")


def _python_mutation(segment: list[str]) -> bool:
    invocation = interpreter_invocation(segment)
    if invocation is not None and invocation.payload is not None:
        return "adw_config" in invocation.payload
    words = [_plain(word) for word in _words(segment)]
    for index, word in enumerate(words):
        if _basename(word) in MODULE_NAMES:
            return words[index + 1:] not in READ_ONLY_ARGS
    return False


def _reparsed(segment: list[str], index: int, cwd: Path) -> bool:
    rest = segment[index + 1:]
    if any(_is_cli(word, cwd) for word in _words(rest)):
        return True
    return any(mutates_policy(inner, cwd) for inner in _segments(" ".join(_words(rest))))


def mutates_policy(segment: list[str], cwd: Path) -> bool:
    """Fail closed, because only status is known to read."""
    words = _words(segment)
    index = _command_word_index(segment)
    if index >= len(words):
        return False
    name, rest = _plain(words[index]), words[index + 1:]
    verb = _basename(name)
    if verb in REPARSE_VERBS:
        return _reparsed(segment, index, cwd)
    if _is_cli(name, cwd):
        return rest not in READ_ONLY_ARGS
    if DYNAMIC_RE.search(name):
        return bool(rest) and rest[0] in SUBCOMMANDS
    if verb in COPY_VERBS:
        return any(_is_cli(word, cwd) for word in rest)
    return (_runs_python(segment) and _python_mutation(segment)) or _wrapped_call(rest)


def _wrapped_call(words: list[str]) -> bool:
    """Scanned because find, timeout, and if can run it."""
    plain = [_plain(word) for word in words]
    return any(
        _basename(word) == CLI_NAME and plain[index + 1:index + 2] and plain[index + 1] in SUBCOMMANDS
        for index, word in enumerate(plain)
    )
