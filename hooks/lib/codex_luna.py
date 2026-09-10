from __future__ import annotations

import uuid
import time
from pathlib import Path
from typing import Any

from . import journal, payloads, session_state
from .luna_feedback import comment_feedback as _comment_feedback
from .luna_feedback import document_feedback as _document_feedback
from .document_review import request_for as document_request
from .hookio import stop_block
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from .luna_provider import JUDGE_TIMEOUT_SECONDS, LunaJudge
from .turn_retry import RETRY_KEY


STATE_KEY = "codex_luna_reviewed_turns"
IN_FLIGHT_KEY = "codex_luna_inflight_reviews"
FAILED_KEY = "codex_luna_failed_reviews"
MAX_REVIEWED_TURNS = 64
MAX_FAILURE_ATTEMPTS = 3
RESERVATION_TTL_SECONDS = JUDGE_TIMEOUT_SECONDS
MAX_SOURCE_CHARS = 24_000
MAX_COMMENT_ROWS = 120
MAX_MESSAGE_CHARS = 900
MAX_REVIEW_REQUESTS = 8
REVIEW_DEADLINE_SECONDS = max(1.0, JUDGE_TIMEOUT_SECONDS - 5)
DOCUMENT_LABEL = "ADW current-session journal"

RESERVED = "reserved"
ALREADY_RESERVED = "already_reserved"
IN_PROGRESS = "in_progress"
RESERVATION_FAILED = "reservation_failed"


class LunaReviewFailure(RuntimeError):
    pass


def _bounded(value: object) -> str:
    text = " ".join(str(value).split())
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_CHARS:
        return text
    return encoded[: MAX_MESSAGE_CHARS - 3].decode("utf-8", errors="ignore") + "..."


def _turn_key(turn_id: str) -> str:
    return turn_id if isinstance(turn_id, str) and turn_id else "<initial>"


def _active_token(row: object, now: float) -> bool:
    if not isinstance(row, dict):
        return False
    turn = row.get("turn_id")
    token = row.get("token")
    expiry = row.get("expires_at")
    return (
        isinstance(turn, str) and bool(turn)
        and isinstance(token, str) and bool(token)
        and isinstance(expiry, (int, float)) and not isinstance(expiry, bool)
        and expiry > now
    )


def _probe_reservation(
    session_id: str, turn_id: str, state_root: str | Path | None,
) -> tuple[str, bool]:
    key = _turn_key(turn_id)
    now = time.time()
    status = "none"
    reclaimed = False

    def update(state: dict) -> dict:
        nonlocal status, reclaimed
        raw = state.get(IN_FLIGHT_KEY, [])
        raw_rows = raw if isinstance(raw, list) else []
        inflight = [row for row in raw_rows if _active_token(row, now)]
        reclaimed = len(inflight) != len(raw_rows)
        if any(row["turn_id"] == key for row in inflight):
            status = IN_PROGRESS
        if reclaimed:
            return {**state, IN_FLIGHT_KEY: inflight}
        return state

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError) as exc:
        raise LunaReviewFailure(f"review reservation state could not be read: {exc}") from exc
    return status, reclaimed


def _reserve_status(
    session_id: str, turn_id: str, state_root: str | Path | None,
) -> tuple[str, str | None]:
    key = _turn_key(turn_id)
    token = uuid.uuid4().hex
    now = time.time()
    status = RESERVATION_FAILED

    def update(state: dict) -> dict:
        nonlocal status
        completed = [row for row in state.get(STATE_KEY, []) if isinstance(row, str)]
        if key in completed:
            status = ALREADY_RESERVED
            return state
        raw = state.get(IN_FLIGHT_KEY, [])
        raw_rows = raw if isinstance(raw, list) else []
        inflight = [row for row in raw_rows if _active_token(row, now)]
        changed = inflight != raw_rows
        if any(row["turn_id"] == key for row in inflight):
            status = IN_PROGRESS
            return {**state, IN_FLIGHT_KEY: inflight} if changed else state
        inflight.append({
            "turn_id": key,
            "token": token,
            "created_at": now,
            "expires_at": now + RESERVATION_TTL_SECONDS,
        })
        status = RESERVED
        return {**state, IN_FLIGHT_KEY: inflight[-MAX_REVIEWED_TURNS:]}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        return RESERVATION_FAILED, None
    return status, token if status == RESERVED else None


def _finish_success(
    session_id: str, turn_id: str, token: str, state_root: str | Path | None,
) -> bool:
    key = _turn_key(turn_id)
    finished = False

    def update(state: dict) -> dict:
        nonlocal finished
        completed = [row for row in state.get(STATE_KEY, []) if isinstance(row, str)]
        now = time.time()
        inflight = [row for row in state.get(IN_FLIGHT_KEY, []) if _active_token(row, now)]
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
        updated = {
            **state,
            STATE_KEY: completed[-MAX_REVIEWED_TURNS:],
            IN_FLIGHT_KEY: remaining,
            FAILED_KEY: failed,
        }
        if state.get(RETRY_KEY) == key:
            updated.pop(RETRY_KEY, None)
        return updated

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
        now = time.time()
        inflight = [row for row in state.get(IN_FLIGHT_KEY, []) if _active_token(row, now)]
        remaining = [row for row in inflight if not (row["turn_id"] == key and row["token"] == token)]
        removed = len(remaining) != len(inflight)
        if removed:
            return {**state, IN_FLIGHT_KEY: remaining}
        return state

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
        return {**state, FAILED_KEY: rows[-MAX_REVIEWED_TURNS:], RETRY_KEY: key}

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
        rows = journal.read(session_id, state_root=state_root)
        overflow = journal.read_overflow(session_id, state_root=state_root)
    except (OSError, ValueError, TypeError) as exc:
        raise LunaReviewFailure(f"current-session journal could not be read: {exc}") from exc
    for marker in overflow:
        if marker.get("path_identity") == journal.OVERFLOW_SENTINEL:
            raise LunaReviewFailure("candidate journal overflow metadata is full; start a new session")
        marker_turn = marker.get("turn_id")
        if not isinstance(marker_turn, str):
            raise LunaReviewFailure("current-session journal overflow state is malformed")
        if marker_turn in {"", turn_id}:
            target = _bounded(marker.get("path_identity") or "an unknown file")
            raise LunaReviewFailure(
                f"the current-session journal was truncated for {target} above {MAX_COMMENT_ROWS} candidates; re-edit the file with fewer candidates or start a new turn"
            )
    matching = [
        row for row in rows
        if row.get("turn_id") in {"", turn_id}
        and row.get("role") in {"comment", "document"}
    ]
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in matching:
        key = journal.candidate_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    if len(unique) > MAX_COMMENT_ROWS:
        raise LunaReviewFailure(
            f"the current-session journal has {len(unique)} candidates, above the limit of {MAX_COMMENT_ROWS}; split the turn"
        )
    return unique


def _document_entries(rows: list[dict[str, Any]], content_limit: int) -> list[str]:
    entries: list[str] = []
    for row in rows:
        if row.get("role") != "document" or not row.get("path") or not row.get("source_context"):
            continue
        path = str(row.get("path", ""))[:512]
        source = str(row.get("source_context", ""))
        if not source.strip():
            continue
        prefix = f"Path: {path}\n\n"[: max(0, content_limit - 1)]
        body_limit = max(1, content_limit - len(prefix))
        for offset in range(0, len(source), body_limit):
            body = source[offset:offset + body_limit]
            context = prefix + body
            if context.strip():
                entries.append(context)
    return entries


def _pack_document_entries(entries: list[str], content_limit: int) -> list[str]:
    packed: list[str] = []
    current = ""
    for entry in entries:
        if current and len(current) + 2 + len(entry) > content_limit:
            packed.append(current)
            current = ""
        current = entry if not current else f"{current}\n\n{entry}"
    if current:
        packed.append(current)
    return packed


def _document_contexts(rows: list[dict[str, Any]]) -> tuple[list[str], bool]:
    limit = max(1, MAX_SOURCE_CHARS)
    label = f"Document: {DOCUMENT_LABEL}\n\n"
    use_document_request = len(label) < limit
    content_limit = limit - len(label) if use_document_request else limit
    entries = _document_entries(rows, content_limit)
    return _pack_document_entries(entries, content_limit), use_document_request


def _document_work(rows: list[dict[str, Any]]) -> list[tuple[JudgeRequest, list[Any]]]:
    contexts, use_document_request = _document_contexts(rows)
    work: list[tuple[JudgeRequest, list[Any]]] = []
    for context in contexts:
        request = (
            document_request(DOCUMENT_LABEL, context)
            if use_document_request
            else JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context=context)
        )
        work.append((request, []))
    return work


def request_for_rows(rows: list[dict[str, Any]]) -> tuple[tuple[JudgeRequest, list[Any]], ...] | None:
    work = _document_work(rows)
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
        work.append((comment_request(tuple(comments)), comments))
    if len(work) > MAX_REVIEW_REQUESTS:
        raise LunaReviewFailure(
            f"the current-turn Luna review needs {len(work)} requests, above the limit of {MAX_REVIEW_REQUESTS}; split the turn"
        )
    return tuple(work) or None


def _review_work(
    payload: object,
    turn_id: str,
    state_root: str | Path | None,
) -> tuple[tuple[tuple[JudgeRequest, list[Any]], ...] | None, str]:
    rows = _journal_rows(payload, turn_id, state_root)
    if not rows:
        return None, "the current-session journal is empty"
    for row in rows:
        role = row.get("role")
        if role == "document" and (
            not isinstance(row.get("path"), str)
            or not row["path"].strip()
            or not isinstance(row.get("source_context"), str)
            or not row["source_context"].strip()
        ):
            raise LunaReviewFailure("the current-session journal has an incomplete document candidate")
        if role == "document" and row.get("source_truncated") is True:
            raise LunaReviewFailure("the current-session journal truncated a document source; split the document before reviewing")
        if role == "comment" and (
            not isinstance(row.get("path"), str)
            or not row["path"].strip()
            or not isinstance(row.get("text"), str)
            or not row["text"].strip()
        ):
            raise LunaReviewFailure("the current-session journal has an incomplete comment candidate")
        if role == "comment" and row.get("text_truncated") is True:
            raise LunaReviewFailure("the current-session journal truncated a comment candidate; shorten the comment before reviewing")
    built = request_for_rows(rows)
    if built is None:
        return None, "the current-session journal has no reviewable candidates"
    return tuple(built), ""


def _reserve_review(
    session_id: str,
    turn_id: str,
    state_root: str | Path | None,
    previous_failure: dict[str, Any] | None,
    attempts: int,
) -> tuple[str | None, dict | None]:
    status, token = _reserve_status(session_id, turn_id, state_root)
    if status == IN_PROGRESS:
        return None, _failure_block("a Luna review is already in progress for this turn; wait for its timeout or retry")
    if status == ALREADY_RESERVED:
        reason = previous_failure.get("reason", "a prior review reservation is unresolved") if previous_failure else "a prior review reservation is unresolved"
        return None, _failure_block(reason, attempts) if previous_failure else {}
    if status == RESERVED and token is not None:
        return token, None
    reason = "the current-turn Luna review reservation could not be acquired"
    _record_failure(session_id, turn_id, reason, state_root)
    return None, _failure_block(reason, attempts + 1)


def _judge_work(provider: object | None, work: tuple[tuple[JudgeRequest, list[Any]], ...]) -> str:
    feedback_rows: list[str] = []
    deadline = time.monotonic() + REVIEW_DEADLINE_SECONDS
    for request, candidates_or_rows in work:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LunaReviewFailure("the Luna review deadline expired before all candidates were reviewed")
        judge = provider if provider is not None else LunaJudge(timeout_seconds=remaining)
        result = judge.judge(request)
        if not isinstance(result, JudgeResult):
            raise ValueError("Luna provider returned an invalid result")
        if request.review_kind is ReviewKind.COMMENT:
            feedback = _comment_feedback(result, tuple(candidates_or_rows))
        else:
            feedback = _document_feedback(result, candidates_or_rows)
        if feedback:
            feedback_rows.append(feedback)
    return "\n\n".join(feedback_rows)


def _preflight(
    payload: object,
    session_id: str,
    turn_id: str,
    state_root: str | Path | None,
) -> tuple[dict[str, Any] | None, int, bool, dict | None]:
    try:
        previous_failure = _failure_entry(session_id, turn_id, state_root)
    except LunaReviewFailure as exc:
        return None, 0, False, _failure_block(exc)
    attempts = previous_failure.get("attempts", 0) if previous_failure else 0
    attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
    if attempts >= MAX_FAILURE_ATTEMPTS:
        reason = previous_failure.get("reason", "repeated provider failure") if previous_failure else "repeated provider failure"
        return previous_failure, attempts, False, _failure_block(reason, attempts)
    reservation_state, reclaimed = _probe_reservation(session_id, turn_id, state_root)
    if reservation_state == IN_PROGRESS:
        return previous_failure, attempts, reclaimed, _failure_block(
            "a Luna review is already in progress for this turn; wait for its timeout or retry"
        )
    if payloads.stop_hook_active(payload) and not previous_failure and not reclaimed:
        return previous_failure, attempts, reclaimed, {}
    return previous_failure, attempts, reclaimed, None


def _perform_review(
    session_id: str,
    turn_id: str,
    state_root: str | Path | None,
    previous_failure: dict[str, Any] | None,
    attempts: int,
    work: tuple[tuple[JudgeRequest, list[Any]], ...],
    provider: object | None,
) -> dict:
    token, reservation_error = _reserve_review(
        session_id, turn_id, state_root, previous_failure, attempts,
    )
    if reservation_error is not None or token is None:
        return reservation_error or _failure_block("the Luna review reservation could not be acquired", attempts + 1)
    try:
        feedback = _judge_work(provider, work)
    except BaseException:
        _rollback(session_id, turn_id, token, state_root)
        raise
    if _finish_success(session_id, turn_id, token, state_root):
        return stop_block(_bounded(feedback)) if feedback else {}
    _rollback(session_id, turn_id, token, state_root)
    reason = "the successful Luna review could not be committed"
    _record_failure(session_id, turn_id, reason, state_root)
    return _failure_block(reason, attempts + 1)


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

    attempts = 0
    try:
        previous_failure, attempts, _reclaimed, preflight_response = _preflight(
            payload, session_id, turn_id, state_root,
        )
        if preflight_response is not None:
            return preflight_response
        work, empty_reason = _review_work(payload, turn_id, state_root)
        if work is None:
            return _failure_block(previous_failure.get("reason", empty_reason), attempts) if previous_failure else {}
        return _perform_review(
            session_id, turn_id, state_root, previous_failure, attempts, work, provider,
        )
    except LunaReviewFailure as exc:
        _record_failure(session_id, turn_id, str(exc), state_root)
        return _failure_block(exc, attempts + 1)
    except Exception as exc:
        _record_failure(session_id, turn_id, str(exc), state_root)
        return _failure_block(exc, attempts + 1)
