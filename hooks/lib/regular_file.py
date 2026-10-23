"""Because opening a FIFO waits for a writer that only the gated command would start, a gate's before-read opens without blocking."""
from __future__ import annotations

import errno
import os
import stat
from typing import BinaryIO

OPEN_FLAGS = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


def open_regular(path: str | os.PathLike[str]) -> BinaryIO:
    """Raises OSError for a FIFO, device, or socket, so every caller's existing unreadable branch applies."""
    descriptor = os.open(path, OPEN_FLAGS)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", os.fspath(path))
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def special_file(path: str | os.PathLike[str]) -> bool:
    """Because a pipe, device, or socket hands written text to a reader that no scan ever sees."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    return not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))


def read_regular_text(path: str | os.PathLike[str], errors: str = "strict") -> str:
    """Because the write the gate judges lands on a link's target too, a link is followed on purpose."""
    with open_regular(path) as handle:
        return handle.read().decode("utf-8", errors=errors)
