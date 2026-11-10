"""Retain verified descriptors because path substitutions must not redirect state reads."""
from __future__ import annotations

import os
from pathlib import Path
import stat

MetadataKey = tuple[int, int, int, int, int, int]
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
LEAF_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def metadata_key(metadata: os.stat_result) -> MetadataKey:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def close_quietly(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _child(parent_fd: int, part: str, create: bool) -> int:
    try:
        child = os.open(part, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(part, 0o700, dir_fd=parent_fd)
        child = os.open(part, DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        if not stat.S_ISDIR(os.fstat(child).st_mode):
            raise ValueError(f"path parent is not a directory: {part}")
    except BaseException:
        close_quietly(child)
        raise
    return child


def _descend(parent_fd: int, part: str, create: bool) -> int:
    try:
        return _child(parent_fd, part, create)
    finally:
        close_quietly(parent_fd)


def open_parent(path: Path, *, create: bool = False) -> int:
    """Reject symlinked parents because reads and replacements must retain their directory identity."""
    if not path.is_absolute():
        raise ValueError(f"path must be absolute: {path}")
    parts = [part for part in path.parent.parts if part not in (path.anchor, "")]
    if any(part in (".", "..") for part in parts):
        raise ValueError("unsafe path component")
    descriptor = os.open(path.anchor or os.sep, DIRECTORY_FLAGS)
    for part in parts:
        descriptor = _descend(descriptor, part, create)
    return descriptor


def open_unchanged(parent_fd: int, name: str, flags: int, expected: os.stat_result, message: str) -> tuple[int, os.stat_result]:
    descriptor = os.open(name, flags | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        if metadata_key(opened) != metadata_key(expected):
            raise ValueError(message)
    except BaseException:
        close_quietly(descriptor)
        raise
    return descriptor, opened


def _drain(descriptor: int, limit: int) -> bytes:
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(descriptor, min(65536, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def read_verified(descriptor: int, expected: os.stat_result, limit: int) -> tuple[bytes, os.stat_result]:
    """Compare both generations because a concurrent rewrite cannot count as stable evidence."""
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or metadata_key(opened) != metadata_key(expected) or opened.st_size > limit:
        raise ValueError("file changed or exceeds its read limit")
    data = _drain(descriptor, limit)
    final = os.fstat(descriptor)
    if len(data) > limit or metadata_key(final) != metadata_key(opened) or len(data) != final.st_size:
        raise ValueError("file changed or exceeds its read limit")
    return data, final


def read_regular(parent_fd: int, name: str, limit: int) -> bytes | None:
    leaf = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(leaf.st_mode):
        return None
    descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | LEAF_FLAGS, dir_fd=parent_fd)
    try:
        return read_verified(descriptor, leaf, limit)[0]
    finally:
        close_quietly(descriptor)
