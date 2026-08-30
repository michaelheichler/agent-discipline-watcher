"""Bounded candidate data every host reads, because a post-write pass and a Stop pass need one record."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any, NamedTuple

from . import session_state
from .narration_candidates import candidates
from .scanner import PROSE_EXTS


STATE_KEY = "claude_candidate_journal"
MAX_ROWS = 120
MAX_STOP_ROWS = 24
MAX_CANDIDATE_CHARS = 320
MAX_DOCUMENT_CHARS = 24_000
MAX_FILE_BYTES = 128 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_LEAF_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class _ReadOutcome(NamedTuple):
    """Carry the status beside the value because a missing file differs from an unreadable one."""

    status: str
    value: tuple[str, str] | None = None


def _metadata_key(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _close_quietly(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _walk_parts(target: Path) -> list[str]:
    """Reject a dot component because it would climb out of the resolved parent."""
    parts = []
    for part in target.parent.parts:
        if part in (target.anchor, ""):
            continue
        if part in (".", ".."):
            raise ValueError("unsafe path component")
        parts.append(part)
    return parts


def _descend(parent_fd: int, part: str) -> int:
    """Check each hop is a directory because a swapped component would escape the walk."""
    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    if not stat.S_ISDIR(os.fstat(child).st_mode):
        _close_quietly(child)
        raise FileNotFoundError(part)
    _close_quietly(parent_fd)
    return child


def _open_parent(target: Path) -> int:
    """Walk part by part because one open on a whole path would follow a swapped symlink."""
    parts = _walk_parts(target)
    parent_fd = os.open(target.anchor or os.sep, _DIRECTORY_FLAGS)
    for part in parts:
        try:
            parent_fd = _descend(parent_fd, part)
        except BaseException:
            _close_quietly(parent_fd)
            raise
    return parent_fd


def _drain(descriptor: int) -> bytearray | None:
    """Read one byte past the cap because a file that grows mid-read must not slip through."""
    data = bytearray()
    while len(data) <= MAX_FILE_BYTES:
        chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    return None if len(data) > MAX_FILE_BYTES else data


def _read_verified(descriptor: int, leaf: os.stat_result) -> _ReadOutcome:
    """Re-stat after the read because a swap mid-read would hash content that never existed."""
    opened = os.fstat(descriptor)
    if _metadata_key(opened) != _metadata_key(leaf) or opened.st_size > MAX_FILE_BYTES:
        return _ReadOutcome("transient")
    data = _drain(descriptor)
    if data is None:
        return _ReadOutcome("transient")
    final = os.fstat(descriptor)
    if _metadata_key(final) != _metadata_key(opened) or len(data) != final.st_size:
        return _ReadOutcome("transient")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        return _ReadOutcome("transient")
    return _ReadOutcome("available", (hashlib.sha256(bytes(data)).hexdigest(), text))


def _read_regular_content(path: Path) -> _ReadOutcome:
    """No-follow descriptors because a symlink swap would read a file outside the journal."""
    parent_fd = -1
    descriptor = -1
    try:
        target = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        parent_fd = _open_parent(target)
        leaf = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(leaf.st_mode):
            return _ReadOutcome("missing")
        descriptor = os.open(target.name, os.O_RDONLY | os.O_NONBLOCK | _LEAF_FLAGS, dir_fd=parent_fd)
        return _read_verified(descriptor, leaf)
    except FileNotFoundError:
        return _ReadOutcome("missing")
    except (OSError, ValueError):
        return _ReadOutcome("transient")
    finally:
        _close_quietly(descriptor)
        _close_quietly(parent_fd)


def _read_content(path: Path) -> _ReadOutcome:
    """Separated because a transient error must not delete a live candidate."""
    return _read_regular_content(path)


def _canonical_path(path: str | Path) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return Path(path)


def _row_identity(row: dict[str, Any]) -> str:
    raw = row.get("path_identity", row.get("path", ""))
    if not isinstance(raw, (str, Path)):
        return ""
    return str(_canonical_path(raw))


def _path_available(identity: str) -> bool:
    if not identity:
        return False
    return _path_status(identity) == "available"


def _path_status(identity: str) -> str:
    if not identity:
        return "missing"
    try:
        metadata = os.stat(_canonical_path(identity), follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "transient"
    except ValueError:
        # Malformed because a stored path names no live file.
        return "missing"
    return "available" if stat.S_ISREG(metadata.st_mode) else "missing"


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("role", "")), _row_identity(row), str(row.get("content_hash", ""))


def _candidate_rows(path: Path, digest: str, text: str, turn_id: str, tool_use_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() == ".py":
        rows.extend({
            "role": "comment",
            "path": candidate.path,
            "path_identity": str(path),
            "line": candidate.line,
            "text": candidate.text[:MAX_CANDIDATE_CHARS],
            "content_hash": digest,
            "turn_id": turn_id,
            "tool_use_id": tool_use_id,
        } for candidate in candidates(str(path), text))
    if path.suffix.lower() in PROSE_EXTS:
        rows.append({
            "role": "document",
            "path": str(path),
            "path_identity": str(path),
            "content_hash": digest,
            "source_context": text[:MAX_DOCUMENT_CHARS],
            "turn_id": turn_id,
            "tool_use_id": tool_use_id,
        })
    return rows


def _stored_rows(state: dict) -> list:
    existing = state.get(STATE_KEY)
    return list(existing) if isinstance(existing, list) else []


def _drop_target(state: dict, target: str) -> dict:
    kept = [
        row for row in _stored_rows(state)
        if not (isinstance(row, dict) and _row_identity(row) == target)
    ]
    return {**state, STATE_KEY: kept}


def _superseded(row: object, target: str, digest: str) -> bool:
    """Drop a changed or vanished row because a stale candidate names a line that moved."""
    if not isinstance(row, dict):
        return False
    identity = _row_identity(row)
    if identity == target:
        return row.get("content_hash") != digest
    return _path_status(identity) == "missing"


def _merged(rows: list, fresh: list, added: list) -> list:
    """Skip a duplicate key because one edit must not report the same candidate twice."""
    keys = {_row_key(row) for row in rows if isinstance(row, dict)}
    for row in fresh:
        if _row_key(row) in keys:
            continue
        rows.append(row)
        added.append(row)
        keys.add(_row_key(row))
    return rows[-MAX_ROWS:]


def _refresher(target: str, digest: str, fresh: list, added: list):
    """Close over the edit because update_state accepts a single-argument callable."""
    def update(state: dict) -> dict:
        kept = [row for row in _stored_rows(state) if not _superseded(row, target, digest)]
        return {**state, STATE_KEY: _merged(kept, fresh, added)}

    return update


def record_edit(session_id: str, turn_id: str, tool_use_id: str, path: str | Path, *, state_root: str | Path | None = None) -> list[dict[str, Any]]:
    if not isinstance(session_id, str) or not session_id:
        return []
    target = _canonical_path(path)
    outcome = _read_content(target)
    if outcome.status == "transient":
        return []
    if outcome.status == "missing" or outcome.value is None:
        session_state.update_state(session_id, lambda state: _drop_target(state, str(target)), state_root)
        return []
    digest, text = outcome.value
    fresh = _candidate_rows(target, digest, text, turn_id, tool_use_id)
    added: list[dict[str, Any]] = []
    session_state.update_state(session_id, _refresher(str(target), digest, fresh, added), state_root)
    return added


def read(session_id: str, *, state_root: str | Path | None = None) -> list[dict[str, Any]]:
    state = session_state.read_state(session_id, state_root)
    rows = state.get(STATE_KEY)
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("role") in {"comment", "document"}]


def read_stop(session_id: str, *, state_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Bounded because an unbounded journal would blow the Stop payload."""
    rows = read(session_id, state_root=state_root)
    bounded: list[dict[str, Any]] = []
    for row in rows:
        if row.get("role") != "document":
            continue
        bounded.append({
            "role": "document",
            "path": str(row.get("path", ""))[:512],
            "content_hash": str(row.get("content_hash", ""))[:64],
            "source_context": str(row.get("source_context", ""))[:MAX_DOCUMENT_CHARS],
        })
    return bounded[-MAX_STOP_ROWS:]


read_for_stop = read_stop
