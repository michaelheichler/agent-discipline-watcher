from __future__ import annotations

import os
import re
import stat

_TOKEN_RE = re.compile(r"[0-9a-f]{16}")


def owned_quarantine_name(name: str, prefix: str, suffix: str) -> bool:
    """Match only ADW's own leaf because a foreign file must survive reclamation."""
    token = name[len(prefix + suffix):] if name.startswith(prefix + suffix) else ""
    return len(token) == 16 and _TOKEN_RE.fullmatch(token) is not None


def _entries(parent_fd: int, prefix: str, suffix: str) -> list[tuple[int, str, int, int]]:
    try:
        names = [name for name in os.listdir(parent_fd) if owned_quarantine_name(name, prefix, suffix)]
    except OSError:
        return []
    found: list[tuple[int, str, int, int]] = []
    for name in names:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            continue
        found.append((metadata.st_mtime_ns, name, metadata.st_size, metadata.st_mode))
    return found


def _drop_leaf(parent_fd: int, name: str, mode: int) -> bool:
    try:
        if stat.S_ISDIR(mode):
            os.rmdir(name, dir_fd=parent_fd)
        elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            os.unlink(name, dir_fd=parent_fd)
        else:
            return False
    except OSError:
        return False
    return True


def reclaim_quarantines(
    parent_fd: int,
    prefix: str,
    suffix: str,
    max_count: int,
    max_bytes: int,
) -> None:
    """Take the bounds as arguments because the caller owns them and tests patch them there."""
    entries = _entries(parent_fd, prefix, suffix)
    total = sum(size for _mtime, _name, size, _mode in entries)
    for _mtime, name, size, mode in sorted(entries):
        if len(entries) <= max_count and total <= max_bytes:
            break
        if not _drop_leaf(parent_fd, name, mode):
            continue
        entries = [entry for entry in entries if entry[1] != name]
        total -= size
