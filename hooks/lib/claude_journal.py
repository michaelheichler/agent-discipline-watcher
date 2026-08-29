"""Bounded candidate data shared by Claude's post-write and Stop agents."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any

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


class _ReadOutcome:
    def __init__(self, status: str, value: tuple[str, str] | None = None) -> None:
        self.status = status
        self.value = value


def _metadata_key(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _read_regular_content(path: Path) -> _ReadOutcome:
    """Read a bounded regular file through no-follow descriptors before decoding."""
    parent_fd = -1
    descriptor = -1
    try:
        target = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        parent_fd = os.open(target.anchor or os.sep, _DIRECTORY_FLAGS)
        for part in target.parent.parts:
            if part in (target.anchor, ""):
                continue
            if part in (".", ".."):
                raise ValueError("unsafe path component")
            child = -1
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=parent_fd)
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    return _ReadOutcome("missing")
                os.close(parent_fd)
                parent_fd = child
                child = -1
            finally:
                if child >= 0:
                    os.close(child)
        try:
            leaf = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return _ReadOutcome("missing")
        if not stat.S_ISREG(leaf.st_mode):
            return _ReadOutcome("missing")
        descriptor = os.open(target.name, os.O_RDONLY | os.O_NONBLOCK | _LEAF_FLAGS, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        if _metadata_key(opened) != _metadata_key(leaf) or opened.st_size > MAX_FILE_BYTES:
            return _ReadOutcome("transient")
        data = bytearray()
        while len(data) <= MAX_FILE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_FILE_BYTES:
            return _ReadOutcome("transient")
        final = os.fstat(descriptor)
        if _metadata_key(final) != _metadata_key(opened) or len(data) != final.st_size:
            return _ReadOutcome("transient")
        try:
            text = bytes(data).decode("utf-8")
        except UnicodeDecodeError:
            return _ReadOutcome("transient")
        return _ReadOutcome("available", (hashlib.sha256(bytes(data)).hexdigest(), text))
    except FileNotFoundError:
        return _ReadOutcome("missing")
    except (OSError, ValueError):
        return _ReadOutcome("transient")
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _read_content(path: Path) -> _ReadOutcome:
    """Separate proven absence from transient/unreadable filesystem errors."""
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
        # Malformed persisted paths cannot identify a live document.
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


def record_edit(
    session_id: str,
    turn_id: str,
    tool_use_id: str,
    path: str | Path,
    *,
    state_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(session_id, str) or not session_id:
        return []
    target = _canonical_path(path)
    outcome = _read_content(target)
    if outcome.status == "transient":
        return []
    read = outcome.value
    if outcome.status == "missing" or read is None:
        def remove_target(state: dict) -> dict:
            existing = state.get(STATE_KEY)
            rows = list(existing) if isinstance(existing, list) else []
            return {
                **state,
                STATE_KEY: [
                    row for row in rows
                    if not (isinstance(row, dict) and _row_identity(row) == str(target))
                ],
            }

        session_state.update_state(session_id, remove_target, state_root)
        return []
    digest, text = read
    fresh = _candidate_rows(target, digest, text, turn_id, tool_use_id)

    added: list[dict[str, Any]] = []

    def update(state: dict) -> dict:
        existing = state.get(STATE_KEY)
        rows = list(existing) if isinstance(existing, list) else []
        rows = [
            row for row in rows
            if not (
                isinstance(row, dict)
                and (
                    (
                        _row_identity(row) == str(target)
                        and row.get("content_hash") != digest
                    )
                    or (
                        _row_identity(row) != str(target)
                        and _path_status(_row_identity(row)) == "missing"
                    )
                )
            )
        ]
        keys = {_row_key(row) for row in rows if isinstance(row, dict)}
        for row in fresh:
            if _row_key(row) not in keys:
                rows.append(row)
                added.append(row)
                keys.add(_row_key(row))
        rows = rows[-MAX_ROWS:]
        return {**state, STATE_KEY: rows}

    session_state.update_state(session_id, update, state_root)
    return added


def read(session_id: str, *, state_root: str | Path | None = None) -> list[dict[str, Any]]:
    state = session_state.read_state(session_id, state_root)
    rows = state.get(STATE_KEY)
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("role") in {"comment", "document"}]


def read_stop(session_id: str, *, state_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Return only bounded document candidates for the current session's Stop review."""
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
