from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

from . import config_roots
from .shell_parse import (
    VERSIONED_PYTHON_RE,
    _basename,
    _command_word_index,
    _is_literal_token,
    _payload_command_index,
    _words,
)
from .protected import _literal
from .shell_syntax import PYTHON_VALUE_OPTION_RE

HOST_FLAGS = frozenset({"--claude", "--codex", "--omp"})
PYTHON_NAMES = frozenset({"python", "python2", "python3"})
PYTHON_EXIT_FLAGS = frozenset({"-", "--help", "--help-env", "--help-xoptions", "--help-all", "--version"})


def untrusted_update(
    segment: list[str],
    home: str | os.PathLike[str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> bool:
    words = _words(segment)
    index = _command_word_index(segment)
    if index < len(words) and _basename(words[index]) == "adw" and words[index + 1:index + 2] == ["update"]:
        return _untrusted_adw_update(segment, words, index, home)
    return _managed_runtime_update(segment, words, home, cwd)


def _untrusted_adw_update(
    segment: list[str], words: list[str], index: int, home: str | os.PathLike[str] | None,
) -> bool:
    if index != 0 or not all(_is_literal_token(token) for token in segment):
        return True
    flags = words[2:]
    if flags not in (["--help"], ["-h"]) and (
        not HOST_FLAGS.intersection(flags) or any(flag not in HOST_FLAGS | {"--dry-run"} for flag in flags)
    ):
        return True
    account_home = Path(home) if home is not None else Path(pwd.getpwuid(os.getuid()).pw_dir)
    return not _managed_executable(Path(words[0]), account_home)


def _managed_runtime_update(
    segment: list[str],
    words: list[str],
    home: str | os.PathLike[str] | None,
    cwd: str | os.PathLike[str] | None,
) -> bool:
    index = _payload_command_index(segment)
    if index >= len(words):
        return False
    interpreter = _basename(words[index])
    if interpreter not in PYTHON_NAMES and VERSIONED_PYTHON_RE.fullmatch(interpreter) is None:
        return False
    script_index = _python_script_index(words, index + 1)
    if script_index is None or words[script_index + 1:script_index + 2] != ["update"]:
        return False
    account_home = Path(home) if home is not None else Path(pwd.getpwuid(os.getuid()).pw_dir)
    target = config_roots.home_relative(words[script_index], account_home) or Path(words[script_index])
    if not target.is_absolute():
        target = Path(cwd) / target if cwd is not None else Path.cwd() / target
    runtime = config_roots.install_root(account_home) / "hooks/update.py"
    try:
        literal = _literal(str(target), account_home)
    except (OSError, ValueError):
        return False
    # Because filesystem names can contain literal tildes.
    return literal is not None and Path(os.path.realpath(literal)) == Path(os.path.realpath(runtime))


def _segment_contexts(
    segments: list[list[str]],
    cwd: str | os.PathLike[str] | None,
    home: str | os.PathLike[str] | None,
) -> list[tuple[list[str], Path]]:
    context_home = home if home is not None else pwd.getpwuid(os.getuid()).pw_dir
    current = Path(cwd) if cwd is not None else Path.cwd()
    contexts = []
    for segment in segments:
        contexts.append((segment, current))
        current = _next_shell_cwd(segment, current, context_home)
    return contexts


def _next_shell_cwd(
    segment: list[str], current: Path, home: str | os.PathLike[str],
) -> Path:
    words = _words(segment)
    index = _command_word_index(segment)
    if index >= len(words) or _basename(words[index]) != "cd":
        return current
    operand = next((word for word in words[index + 1:] if word == "--" or not word.startswith("-")), None)
    if operand == "--":
        operand_index = words.index(operand, index + 1) + 1
        operand = words[operand_index] if operand_index < len(words) else None
    if operand is None:
        # Because filesystem names can contain literal tildes.
        return Path(os.path.realpath(Path(home))) if words[index + 1:] in ([], ["--"]) else current
    candidate = config_roots.home_relative(operand, Path(home)) or Path(operand)
    if not _is_literal_token(str(candidate)):
        return current
    try:
        candidate = _literal(str(candidate), home) if str(candidate).startswith("~") else candidate
        if candidate is None:
            return current
        if not candidate.is_absolute():
            candidate = current / candidate
        literal = _literal(str(candidate), home)
        # Because filesystem names can contain literal tildes.
        return current if literal is None else Path(os.path.realpath(literal))
    except (OSError, ValueError):
        return current


def _python_script_index(words: list[str], start: int) -> int | None:
    expecting_value = False
    for index in range(start, len(words)):
        token = words[index]
        if expecting_value:
            expecting_value = False
            continue
        if token == "--":
            return index + 1 if index + 1 < len(words) else None
        if token in PYTHON_EXIT_FLAGS:
            return None
        option = PYTHON_VALUE_OPTION_RE.match(token)
        if option is not None:
            if option[1] in {"c", "m"} or set("hV").intersection(option[0][1:-1]):
                return None
            expecting_value = option.end() == len(token)
            continue
        if token.startswith("-"):
            if not token.startswith("--") and set("hV").intersection(token[1:]):
                return None
            continue
        return index
    return None


def _owned(path: Path, directory: bool = False) -> bool:
    info = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    return expected_type(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022


def _managed_executable(command: Path, home: Path) -> bool:
    root = config_roots.install_root(home)
    executable = root / "bin/adw"
    link = home / ".adw/bin/adw"
    if command not in {executable, link}:
        return False
    try:
        directories = [home, home / ".adw", root.parent, root, root / "bin"]
        if command == link:
            directories.append(link.parent)
            if not link.is_symlink() or link.lstat().st_uid != os.getuid() or link.resolve() != executable:
                return False
        marker = root / ".adw-install-marker"
        return (
            all(_owned(path, directory=True) for path in directories)
            and _owned(executable) and bool(executable.stat().st_mode & stat.S_IXUSR)
            and _owned(marker) and marker.read_text(encoding="utf-8") == "agent-discipline-watcher\n"
        )
    except (OSError, ValueError, UnicodeError):
        return False
