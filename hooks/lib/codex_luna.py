"""One Luna review for each completed Codex interaction."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import claude_journal, payloads, session_state
from .claude_luna import _comment_feedback, _document_feedback
from .config import effective_hook_config
from .document_review import request_for as document_request
from .hookio import stop_block
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from .luna_provider import LunaJudge


STATE_KEY = "codex_luna_reviewed_turns"
MAX_REVIEWED_TURNS = 64
MAX_SOURCE_CHARS = 24_000
MAX_COMMENT_ROWS = 120
MAX_MESSAGE_CHARS = 900


def _bounded(value: object) -> str:
    text = " ".join(str(value).split())
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_CHARS:
        return text
    return encoded[: MAX_MESSAGE_CHARS - 3].decode("utf-8", errors="ignore") + "..."


def _turn_key(turn_id: str) -> str:
    return turn_id if isinstance(turn_id, str) and turn_id else "<initial>"


def _reserve(session_id: str, turn_id: str, state_root: str | Path | None) -> bool:
    key = _turn_key(turn_id)
    reserved = False

    def update(state: dict) -> dict:
        nonlocal reserved
        current = state.get(STATE_KEY)
        rows = [row for row in current if isinstance(row, str)] if isinstance(current, list) else []
        if key in rows:
            return state
        rows.append(key)
        reserved = True
        return {**state, STATE_KEY: rows[-MAX_REVIEWED_TURNS:]}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        return False
    return reserved


def _journal_rows(
    payload: object,
    turn_id: str,
    state_root: str | Path | None,
) -> list[dict[str, Any]]:
    if type(payload) is not dict or payloads.stop_hook_active(payload):
        return []
    session_id = payloads.session_id(payload)
    if not session_id:
        return []
    try:
        rows = claude_journal.read(session_id, state_root=state_root)
    except (OSError, ValueError, TypeError):
        return []
    matching = [
        row for row in rows
        if row.get("turn_id") in {"", turn_id}
        and row.get("role") in {"comment", "document"}
    ]
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in matching:
        key = (
            str(row.get("role", "")),
            str(row.get("path_identity", row.get("path", ""))),
            str(row.get("content_hash", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[-MAX_COMMENT_ROWS:]


def request_for_rows(rows: list[dict[str, Any]]) -> tuple[JudgeRequest, list[Any]] | None:
    documents = [
        f"Path: {str(row.get('path', ''))[:512]}\n\n{str(row.get('source_context', ''))[:MAX_SOURCE_CHARS]}"
        for row in rows
        if row.get("role") == "document" and row.get("path") and row.get("source_context")
    ]
    if documents:
        source = "\n\n".join(documents)[:MAX_SOURCE_CHARS]
        if source.strip():
            return document_request("ADW current-session journal", source), rows
    comments = [
        Candidate(
            str(row.get("path", ""))[:512],
            int(row.get("line", 1)) if isinstance(row.get("line"), int) else 1,
            str(row.get("text", ""))[:320],
        )
        for row in rows
        if row.get("role") == "comment" and row.get("text")
    ]
    if comments:
        return comment_request(tuple(comments)), comments
    return None


def review(
    payload: object,
    *,
    turn_id: str,
    state_root: str | Path | None = None,
    provider: object | None = None,
) -> dict:
    session_id = payloads.session_id(payload)
    if not session_id or payloads.stop_hook_active(payload):
        return {}
    rows = _journal_rows(payload, turn_id, state_root)
    if not rows or not _reserve(session_id, turn_id, state_root):
        return {}
    built = request_for_rows(rows)
    if built is None:
        return {}
    request, candidates_or_rows = built
    judge = provider or LunaJudge()
    try:
        result = judge.judge(request)
        if not isinstance(result, JudgeResult):
            raise ValueError("Luna provider returned an invalid result")
        if request.review_kind is ReviewKind.COMMENT:
            feedback = _comment_feedback(result, tuple(candidates_or_rows))
        else:
            feedback = _document_feedback(result, rows)
        return stop_block(_bounded(feedback)) if feedback else {}
    except Exception as exc:
        detail = _bounded(exc)
        return stop_block(
            _bounded(
                "agent-discipline-watcher Luna review unavailable: "
                f"{detail}. Complete Codex ChatGPT subscription login or reinstall the ADW runtime, then retry."
            )
        )


def state_root_for(payload: object, explicit: str | Path | None = None) -> str | Path | None:
    if explicit is not None:
        return explicit
    cwd = payloads.cwd(payload)
    try:
        return effective_hook_config({}, cwd or None).get("state_root")
    except (OSError, ValueError, TypeError):
        return None
