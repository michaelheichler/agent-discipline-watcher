"""Bounded candidate data shared by Claude's post-write and Stop agents."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import session_state
from .narration_candidates import candidates
from .scanner import PROSE_EXTS


STATE_KEY = "claude_candidate_journal"
MAX_ROWS = 120
MAX_STOP_ROWS = 24
MAX_CANDIDATE_CHARS = 320
MAX_DOCUMENT_CHARS = 24_000


def _content(path: Path) -> tuple[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), text


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
    try:
        return _canonical_path(identity).is_file()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


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
    read = _content(target)
    if read is None:
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
                        and not _path_available(_row_identity(row))
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
