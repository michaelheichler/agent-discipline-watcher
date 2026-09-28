"""Separate from the worker, because tests must import it without the Mac-only MLX wheel."""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

RECORD_NAME = "server.json"
LOCK_NAME = "server.lock"
SUPERVISOR_LOCK_NAME = "supervisor.lock"
WATCH_SECONDS = 5.0
MISSES_BEFORE_EXIT = 2


def named_in_record(root: Path, pid: int) -> bool:
    try:
        row = json.loads((root / RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return False
    return isinstance(row, dict) and row.get("pid") == pid


def _supervisor_holds(root: Path) -> bool:
    """Probed under the lifecycle lock, because a supervisor takes its own lock only while it holds that one."""
    with (root / SUPERVISOR_LOCK_NAME).open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False


def supervised(root: Path) -> bool:
    with (root / LOCK_NAME).open("a", encoding="utf-8") as lifecycle:
        fcntl.flock(lifecycle.fileno(), fcntl.LOCK_EX)
        try:
            return _supervisor_holds(root)
        finally:
            fcntl.flock(lifecycle.fileno(), fcntl.LOCK_UN)


def still_owned(root: Path, pid: int) -> bool:
    return named_in_record(root, pid) and supervised(root)


def watch(root: Path, stop: Callable[[], None], period: float = WATCH_SECONDS) -> None:
    """Two misses in a row, because the supervisor writes the record a moment after the launch."""
    misses = 0
    while True:
        time.sleep(period)
        misses = 0 if still_owned(root, os.getpid()) else misses + 1
        if misses >= MISSES_BEFORE_EXIT:
            stop()
            return


def start(root: Path, stop: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=watch, args=(root, stop), daemon=True)
    thread.start()
    return thread
