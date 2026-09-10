from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

from .shell_parse import _basename, _command_word_index, _is_literal_token, _words

HOST_FLAGS = frozenset({"--claude", "--codex", "--omp"})


def untrusted_update(segment: list[str], home: str | os.PathLike[str] | None = None) -> bool:
    words = _words(segment)
    index = _command_word_index(segment)
    if index >= len(words) or _basename(words[index]) != "adw":
        return False
    if words[index + 1:index + 2] != ["update"]:
        return False
    if index != 0 or not all(_is_literal_token(token) for token in segment):
        return True
    flags = words[2:]
    if flags not in (["--help"], ["-h"]) and (
        not HOST_FLAGS.intersection(flags) or any(flag not in HOST_FLAGS | {"--dry-run"} for flag in flags)
    ):
        return True
    account_home = Path(home) if home is not None else Path(pwd.getpwuid(os.getuid()).pw_dir)
    return not _managed_executable(Path(words[0]), account_home)


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
