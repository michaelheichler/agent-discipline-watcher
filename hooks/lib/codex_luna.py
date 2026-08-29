"""One Luna review for each completed Codex interaction."""
from __future__ import annotations

import uuid
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
IN_FLIGHT_KEY = "codex_luna_inflight_reviews"
FAILED_KEY = "codex_luna_failed_reviews"
MAX_REVIEWED_TURNS = 64
MAX_FAILURE_ATTEMPTS = 3
MAX_SOURCE_CHARS = 24_000
MAX_COMMENT_ROWS = 120
MAX_MESSAGE_CHARS = 900

RESERVED = "reserved"
ALREADY_RESERVED = "already_reserved"
RESERVATION_FAILED = "reservation_failed"


class LunaReviewFailure(RuntimeError):
    """A current-turn review dependency failed and must remain visible to Stop."""


def _bounded(value: object) -> str:
    text = " ".join(str(value).split())
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_CHARS:
        return text
    return encoded[: MAX_MESSAGE_CHARS - 3].decode("utf-8", errors="ignore") + "..."


def _turn_key(turn_id: str) -> str:
    return turn_id if isinstance(turn_id, str) and turn_id else "<initial>"


def _reserve_status(
    session_id: str, turn_id: str, state_root: str | Path | None,
) -> tuple[str, str | None]:
    key = _turn_key(turn_id)
    token = uuid.uuid4().hex
    status = RESERVATION_FAILED

    def update(state: dict) -> dict:
        nonlocal status
        completed = [row for row in state.get(STATE_KEY, []) if isinstance(row, str)]
        if key in completed:
            status = ALREADY_RESERVED
            return state
        inflight = [
            row for row in state.get(IN_FLIGHT_KEY, [])
            if isinstance(row, dict) and isinstance(row.get("turn_id"), str) and isinstance(row.get("token"), str)
        ]
        if any(row["turn_id"] == key for row in inflight):
            status = ALREADY_RESERVED
            return state
        inflight.append({"turn_id": key, "token": token})
        status = RESERVED
        return {**state, IN_FLIGHT_KEY: inflight[-MAX_REVIEWED_TURNS:]}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        return RESERVATION_FAILED, None
    return status, token if status == RESERVED else None


def _reserve(session_id: str, turn_id: str, state_root: str | Path | None) -> bool:
    return _reserve_status(session_id, turn_id, state_root)[0] == RESERVED


def _finish_success(
    session_id: str, turn_id: str, token: str, state_root: str | Path | None,
) -> bool:
    key = _turn_key(turn_id)
    finished = False

    def update(state: dict) -> dict:
        nonlocal finished
        completed = [row for row in state.get(STATE_KEY, []) if isinstance(row, str)]
        inflight = [
            row for row in state.get(IN_FLIGHT_KEY, [])
            if isinstance(row, dict) and isinstance(row.get("turn_id"), str) and isinstance(row.get("token"), str)
        ]
        owned = any(row["turn_id"] == key and row["token"] == token for row in inflight)
        if not owned:
            return state
        remaining = [row for row in inflight if not (row["turn_id"] == key and row["token"] == token)]
        if key not in completed:
            completed.append(key)
        failed = [
            row for row in state.get(FAILED_KEY, [])
            if isinstance(row, dict) and row.get("turn_id") != key
        ]
        finished = True
        return {**state, STATE_KEY: completed[-MAX_REVIEWED_TURNS:], IN_FLIGHT_KEY: remaining, FAILED_KEY: failed}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        return False
    return finished


def _rollback(
    session_id: str, turn_id: str, token: str, state_root: str | Path | None,
) -> bool:
    key = _turn_key(turn_id)
    removed = False

    def update(state: dict) -> dict:
        nonlocal removed
        inflight = [
            row for row in state.get(IN_FLIGHT_KEY, [])
            if isinstance(row, dict) and isinstance(row.get("turn_id"), str) and isinstance(row.get("token"), str)
        ]
        remaining = [row for row in inflight if not (row["turn_id"] == key and row["token"] == token)]
        removed = len(remaining) != len(inflight)
        return {**state, IN_FLIGHT_KEY: remaining} if removed else state

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        return False
    return removed


def _failure_entry(session_id: str, turn_id: str, state_root: str | Path | None) -> dict[str, Any] | None:
    key = _turn_key(turn_id)
    try:
        state = session_state.read_state(session_id, state_root)
    except (OSError, ValueError, TypeError) as exc:
        raise LunaReviewFailure(f"review failure state could not be read: {exc}") from exc
    rows = state.get(FAILED_KEY)
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, dict) and row.get("turn_id") == key), None)


def _record_failure(
    session_id: str, turn_id: str, reason: str, state_root: str | Path | None,
) -> None:
    key = _turn_key(turn_id)
    bounded_reason = _bounded(reason)

    def update(state: dict) -> dict:
        rows = [row for row in state.get(FAILED_KEY, []) if isinstance(row, dict)]
        previous = next((row for row in rows if row.get("turn_id") == key), None)
        attempts = previous.get("attempts", 0) if isinstance(previous, dict) else 0
        attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
        rows = [row for row in rows if row.get("turn_id") != key]
        rows.append({"turn_id": key, "attempts": attempts + 1, "reason": bounded_reason})
        return {**state, FAILED_KEY: rows[-MAX_REVIEWED_TURNS:]}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        pass


def _failure_block(reason: object, attempts: int = 0) -> dict:
    suffix = f" Luna retry limit reached after {MAX_FAILURE_ATTEMPTS} attempts." if attempts >= MAX_FAILURE_ATTEMPTS else ""
    return stop_block(_bounded(f"agent-discipline-watcher Luna review unavailable: {reason}.{suffix} Complete Codex ChatGPT subscription login or reinstall the ADW runtime, then retry."))


def _journal_rows(
    payload: object,
    turn_id: str,
    state_root: str | Path | None,
) -> list[dict[str, Any]]:
    if type(payload) is not dict:
        return []
    session_id = payloads.session_id(payload)
    if not session_id:
        return []
    try:
        rows = claude_journal.read(session_id, state_root=state_root)
    except (OSError, ValueError, TypeError) as exc:
        raise LunaReviewFailure(f"current-session journal could not be read: {exc}") from exc
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
    if not session_id:
        return {}

    try:
        previous_failure = _failure_entry(session_id, turn_id, state_root)
    except LunaReviewFailure as exc:
        return _failure_block(exc)
    attempts = previous_failure.get("attempts", 0) if previous_failure else 0
    attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
    if attempts >= MAX_FAILURE_ATTEMPTS:
        return _failure_block(previous_failure.get("reason", "repeated provider failure"), attempts)
    if payloads.stop_hook_active(payload) and not previous_failure:
        return {}

    try:
        rows = _journal_rows(payload, turn_id, state_root)
        if not rows:
            return _failure_block(previous_failure.get("reason", "the current-session journal is empty"), attempts) if previous_failure else {}
        built = request_for_rows(rows)
        if built is None:
            return _failure_block(previous_failure.get("reason", "the current-session journal has no reviewable candidates"), attempts) if previous_failure else {}
        request, candidates_or_rows = built
        status, token = _reserve_status(session_id, turn_id, state_root)
        if status == ALREADY_RESERVED:
            return _failure_block(previous_failure.get("reason", "a prior review reservation is unresolved"), attempts) if previous_failure else {}
        if status != RESERVED or token is None:
            reason = "the current-turn Luna review reservation could not be acquired"
            _record_failure(session_id, turn_id, reason, state_root)
            return _failure_block(reason, attempts + 1)
        judge = provider or LunaJudge()
        result = judge.judge(request)
        if not isinstance(result, JudgeResult):
            raise ValueError("Luna provider returned an invalid result")
        if request.review_kind is ReviewKind.COMMENT:
            feedback = _comment_feedback(result, tuple(candidates_or_rows))
        else:
            feedback = _document_feedback(result, rows)
        if not _finish_success(session_id, turn_id, token, state_root):
            _rollback(session_id, turn_id, token, state_root)
            reason = "the successful Luna review could not be committed"
            _record_failure(session_id, turn_id, reason, state_root)
            return _failure_block(reason, attempts + 1)
        return stop_block(_bounded(feedback)) if feedback else {}
    except LunaReviewFailure as exc:
        _record_failure(session_id, turn_id, str(exc), state_root)
        return _failure_block(exc, attempts + 1)
    except Exception as exc:
        _rollback(session_id, turn_id, token if "token" in locals() and isinstance(token, str) else "", state_root)
        _record_failure(session_id, turn_id, str(exc), state_root)
        return _failure_block(exc, attempts + 1)


def state_root_for(payload: object, explicit: str | Path | None = None) -> str | Path | None:
    if explicit is not None:
        return explicit
    cwd = payloads.cwd(payload)
    try:
        return effective_hook_config({}, cwd or None).get("state_root")
    except (OSError, ValueError, TypeError):
        return None
