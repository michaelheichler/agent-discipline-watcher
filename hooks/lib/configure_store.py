"""Persistence for the configuration bridge, kept apart because a lock and a replace carry no policy."""
from __future__ import annotations

import fcntl
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    from .configure_policy import MISSING, ConfigureError
except ImportError:
    from configure_policy import MISSING, ConfigureError

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _open_lock(lock_path: Path) -> int:
    try:
        return os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise ConfigureError("lock_failed", "could not open the configuration lock") from exc


def _acquire(stream) -> None:
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        raise ConfigureError("lock_failed", "could not acquire the configuration lock") from exc


def _release(stream) -> None:
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        stream.close()


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold one lock across read, compare, and replace because a split write would race."""
    stream = os.fdopen(_open_lock(Path(f"{path}.lock")), "r+")
    try:
        _acquire(stream)
        yield
    finally:
        _release(stream)


def _sync_parent(path: Path) -> None:
    try:
        directory = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink()
    except OSError:
        pass


def atomic_write(path: Path, data: bytes) -> None:
    """Replace through a same-directory temporary because a partial write would corrupt policy."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _sync_parent(path)
    except OSError as exc:
        raise ConfigureError("write_failed", "project config could not be replaced") from exc
    finally:
        _discard(temporary)


def expected_digest(request: dict[str, object]) -> str | None:
    """Demand the digest because a blind write would silently discard a concurrent edit."""
    expected = request.get("expected_digest", MISSING)
    if expected is MISSING:
        raise ConfigureError("expected_digest_required", "write requires expected_digest")
    if expected is None:
        return None
    if type(expected) is not str or DIGEST_RE.fullmatch(expected) is None:
        raise ConfigureError("invalid_digest", "expected_digest must be a SHA-256 hex digest or null")
    return expected
