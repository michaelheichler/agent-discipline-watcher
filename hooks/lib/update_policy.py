from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

from .shell_parse import (
    VERSIONED_PYTHON_RE,
    _basename,
    _command_word_index,
    _is_literal_token,
    _payload_command_index,
    _words,
)
from .protected import _literal, _normalize

HOST_FLAGS = frozenset({"--claude", "--codex", "--omp"})
PYTHON_NAMES = frozenset({"python", "python2", "python3"})
PYTHON_VALUE_FLAGS = frozenset({"-c", "-m", "-W", "-X"})


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
    target = _expand_home_token(words[script_index], account_home)
    if not target.is_absolute():
        target = Path(cwd) / target if cwd is not None else Path.cwd() / target
    runtime = account_home / ".adw/install/agent-discipline-watcher/hooks/update.py"
    try:
        literal = _literal(str(target), account_home)
    except (OSError, ValueError):
        return False
    return literal is not None and _normalize(literal) == _normalize(runtime)


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
    segment: list[str], current: Path, home: str | os.PathLike[str] | None,
) -> Path:
    words = _words(segment)
    index = _command_word_index(segment)
    if index >= len(words) or _basename(words[index]) != "cd":
        return current
    operand = next((word for word in words[index + 1:] if word == "--" or not word.startswith("-")), None)
    if operand == "--":
        operand_index = words.index(operand, index + 1) + 1
        operand = words[operand_index] if operand_index < len(words) else None
    if operand is None or not _is_literal_token(operand):
        return current
    try:
        candidate = _literal(operand, home) if operand.startswith("~") else Path(operand)
        if candidate is None:
            return current
        if not candidate.is_absolute():
            candidate = current / candidate
        literal = _literal(str(candidate), home)
        return current if literal is None else _normalize(literal)
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
        if token in PYTHON_VALUE_FLAGS:
            if token in {"-c", "-m"}:
                return None
            expecting_value = True
            continue
        if token.startswith("-W") or token.startswith("-X"):
            continue
        if token.startswith("-"):
            continue
        return index
    return None


def _expand_home_token(value: str, home: Path) -> Path:
    suffix: str | None = None
    if value in {"~", "$HOME", "${HOME}"}:
        suffix = ""
    elif value.startswith("~/"):
        suffix = value[2:]
    elif value.startswith("$HOME/"):
        suffix = value[6:]
    elif value.startswith("${HOME}/"):
        suffix = value[8:]
    return Path(value) if suffix is None else home / suffix

def _owned(path: Path, directory: bool = False) -> bool:
    info = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    return expected_type(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022


def _managed_executable(command: Path, home: Path) -> bool:
    root = home / ".adw/install/agent-discipline-watcher"
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
