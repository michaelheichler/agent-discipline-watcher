from __future__ import annotations

import uuid
import time
from pathlib import Path
from typing import Any

from . import journal, payloads, session_state
from .codex_luna_documents import feedback_sources
from .config import effective_hook_config
from .document_review import data_boundary_enabled, document_work
from .luna_feedback import comment_feedback as _comment_feedback
from .luna_feedback import document_feedback as _document_feedback
from .luna_feedback import pattern_feedback as _pattern_feedback
from .hookio import stop_block, system_message
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from .pattern_judge import PatternCandidate, request_for as pattern_request
from .pattern_semantic import load_exemplars, load_manifest, rule_blocks, rule_prompt
from .luna_provider import JUDGE_TIMEOUT_SECONDS, LunaJudge
from .luna_storage import LunaProviderFailure
from .turn_retry import (
    FAILED_KEY, RETRY_KEY, pending_feedback, provider_cooling, record_provider_outage,
    failure_entry as _failure_entry, record_failure as _record_failure,
)


STATE_KEY = "codex_luna_reviewed_turns"
IN_FLIGHT_KEY = "codex_luna_inflight_reviews"
MAX_REVIEWED_TURNS = 64
RESERVATION_TTL_SECONDS = JUDGE_TIMEOUT_SECONDS
MAX_SOURCE_CHARS = 24_000
MAX_COMMENT_ROWS = 120
MAX_MESSAGE_CHARS = 900
MAX_REVIEW_REQUESTS = 8
REVIEW_DEADLINE_SECONDS = max(1.0, JUDGE_TIMEOUT_SECONDS - 5)
DOCUMENT_LABEL = "ADW current-session journal"
UNRESOLVED_CATEGORIES = frozenset({"timeout", "malformed", "worker_protocol", "policy"})

RESERVED = "reserved"
ALREADY_RESERVED = "already_reserved"
IN_PROGRESS = "in_progress"
RESERVATION_FAILED = "reservation_failed"


class LunaReviewFailure(RuntimeError):
    pass


class InterruptedReview(LunaProviderFailure):
    def __init__(self, cause: LunaProviderFailure, feedback: str, confirmed: list[dict]) -> None:
        super().__init__(str(cause), category=cause.category)
        self.feedback = feedback
        self.confirmed = confirmed


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


def _live_inflight(state: dict, now: float) -> tuple[list[dict], bool]:
    raw = state.get(IN_FLIGHT_KEY, [])
    raw_rows = raw if isinstance(raw, list) else []
    inflight = [row for row in raw_rows if _active_token(row, now)]
    return inflight, inflight != raw_rows


def _probe_reservation(
    session_id: str, turn_id: str, state_root: str | Path | None,
) -> tuple[str, bool]:
    key = _turn_key(turn_id)
    now = time.time()
    status = "none"
    reclaimed = False

    def update(state: dict) -> dict:
        nonlocal status, reclaimed
        inflight, reclaimed = _live_inflight(state, now)
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


def _reserved_state(state: dict, key: str, token: str, now: float) -> tuple[str, dict]:
    if key in [row for row in state.get(STATE_KEY, []) if isinstance(row, str)]:
        return ALREADY_RESERVED, state
    inflight, changed = _live_inflight(state, now)
    if any(row["turn_id"] == key for row in inflight):
        return IN_PROGRESS, ({**state, IN_FLIGHT_KEY: inflight} if changed else state)
    inflight.append({
        "turn_id": key, "token": token, "created_at": now, "expires_at": now + RESERVATION_TTL_SECONDS,
    })
    return RESERVED, {**state, IN_FLIGHT_KEY: inflight[-MAX_REVIEWED_TURNS:]}


def _reserve_status(
    session_id: str, turn_id: str, state_root: str | Path | None,
) -> tuple[str, str | None]:
    key = _turn_key(turn_id)
    token = uuid.uuid4().hex
    now = time.time()
    status = RESERVATION_FAILED

    def update(state: dict) -> dict:
        nonlocal status
        status, updated = _reserved_state(state, key, token, now)
        return updated

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        return RESERVATION_FAILED, None
    return status, token if status == RESERVED else None


def _completed_state(state: dict, key: str, token: str) -> dict | None:
    """None unless this token owns the turn, because a stale finish must not commit."""
    inflight = [row for row in state.get(IN_FLIGHT_KEY, []) if _active_token(row, time.time())]
    if not any(row["turn_id"] == key and row["token"] == token for row in inflight):
        return None
    completed = [row for row in state.get(STATE_KEY, []) if isinstance(row, str)]
    if key not in completed:
        completed.append(key)
    updated = {
        **state,
        STATE_KEY: completed[-MAX_REVIEWED_TURNS:],
        IN_FLIGHT_KEY: [row for row in inflight if not (row["turn_id"] == key and row["token"] == token)],
        FAILED_KEY: [row for row in state.get(FAILED_KEY, []) if isinstance(row, dict) and row.get("turn_id") != key],
    }
    if state.get(RETRY_KEY) == key:
        updated.pop(RETRY_KEY, None)
    return updated


def _finish_success(
    session_id: str, turn_id: str, token: str, state_root: str | Path | None,
) -> bool:
    key = _turn_key(turn_id)
    finished = False

    def update(state: dict) -> dict:
        nonlocal finished
        updated = _completed_state(state, key, token)
        finished = updated is not None
        return state if updated is None else updated

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


def _failure_block(reason: object, attempts: int = 0) -> dict:
    suffix = f" Review attempt {attempts} failed." if attempts else ""
    return stop_block(_bounded(f"agent-discipline-watcher Luna review unavailable: {reason}.{suffix} Correct the review input or state and retry."))


def _reject_overflow(overflow: list[dict[str, Any]]) -> None:
    for marker in overflow:
        if marker.get("path_identity") == journal.OVERFLOW_SENTINEL:
            raise LunaReviewFailure(
                "candidate journal overflow metadata is full; start a new Codex session because this session cannot recover all omitted files"
            )
        if not isinstance(marker.get("turn_id"), str):
            raise LunaReviewFailure("current-session journal overflow state is malformed")
        target = _bounded(marker.get("path_identity") or "an unknown file")
        raise LunaReviewFailure(
            f"the current-session journal was truncated for {target} above {MAX_COMMENT_ROWS} candidates; re-edit the affected file with fewer candidates before retrying"
        )


def _unique_turn_rows(rows: list[dict[str, Any]], turn_id: str) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("turn_id") in {"", turn_id} and row.get("role") in {"comment", "document", "pattern"}:
            unique.setdefault(journal.candidate_key(row), row)
    if len(unique) > MAX_COMMENT_ROWS:
        raise LunaReviewFailure(
            f"the current-session journal has {len(unique)} candidates, above the limit of {MAX_COMMENT_ROWS}; reduce candidates in the affected files before retrying"
        )
    return list(unique.values())


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
    _reject_overflow(overflow)
    return _unique_turn_rows(rows, turn_id)


def _pattern_work(rows: list[dict[str, Any]]) -> list[tuple[JudgeRequest, list[Any]]]:
    """One request per rule, because each carries its examples."""
    grouped: dict[str, list[PatternCandidate]] = {}
    for row in rows:
        if row.get("role") == "pattern":
            line = row.get("line") if isinstance(row.get("line"), int) else 1
            candidate = PatternCandidate(str(row.get("path", ""))[:512], line, str(row.get("text", ""))[:320])
            grouped.setdefault(str(row.get("rule")), []).append(candidate)
    if not grouped:
        return []
    exemplars, manifest = load_exemplars(), load_manifest()
    return [
        (pattern_request(rule_prompt(rule, exemplars, manifest), tuple(found)), found)
        for rule, found in sorted(grouped.items())
        if rule in manifest["rules"]
    ]


def request_for_rows(rows: list[dict[str, Any]]) -> tuple[tuple[JudgeRequest, list[Any]], ...] | None:
    work = document_work(rows, MAX_SOURCE_CHARS, DOCUMENT_LABEL)
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
    work.extend(_pattern_work(rows))
    if len(work) > MAX_REVIEW_REQUESTS:
        raise LunaReviewFailure(
            f"the current-turn Luna review needs {len(work)} requests, above the limit of {MAX_REVIEW_REQUESTS}; shorten documents or reduce edited files before retrying"
        )
    return tuple(work) or None


def _filled(row: dict[str, Any], field: str) -> bool:
    value = row.get(field)
    return isinstance(value, str) and bool(value.strip())


def _validate_row(row: dict[str, Any]) -> None:
    role = row.get("role")
    if role == "document" and not (_filled(row, "path") and _filled(row, "source_context")):
        raise LunaReviewFailure("the current-session journal has an incomplete document candidate")
    if role == "document" and journal.document_source_truncated(row):
        raise LunaReviewFailure("the current-session journal truncated a document source; split the document before reviewing")
    if role == "comment" and not (_filled(row, "path") and _filled(row, "text")):
        raise LunaReviewFailure("the current-session journal has an incomplete comment candidate")
    if role == "comment" and row.get("text_truncated") is True:
        raise LunaReviewFailure("the current-session journal truncated a comment candidate; shorten the comment before reviewing")
    if role == "pattern" and not all(_filled(row, field) for field in ("path", "text", "rule")):
        raise LunaReviewFailure("the current-session journal has an incomplete pattern candidate")


def _review_work(
    payload: object,
    turn_id: str,
    state_root: str | Path | None,
) -> tuple[tuple[tuple[JudgeRequest, list[Any]], ...] | None, str]:
    rows = _journal_rows(payload, turn_id, state_root)
    if not rows:
        return None, "the current-session journal is empty"
    for row in rows:
        _validate_row(row)
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


def _feedback(request: JudgeRequest, result: JudgeResult, sources: list[Any]) -> str:
    if request.review_kind is ReviewKind.COMMENT:
        return _comment_feedback(result, tuple(sources))
    if request.review_kind is ReviewKind.PATTERN:
        return _pattern_feedback(result, tuple(sources), request.rule_action)
    return _document_feedback(result, sources)


def _judged(provider: object | None, request: JudgeRequest, deadline: float) -> JudgeResult:
    """Raised bare, because the caller holds the partial feedback."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LunaProviderFailure("the Luna review deadline expired before all candidates were reviewed", category="timeout")
    judge = provider if provider is not None else LunaJudge(timeout_seconds=remaining)
    result = judge.judge(request)
    if not isinstance(result, JudgeResult):
        raise LunaProviderFailure("Luna provider returned an invalid result", category="worker_protocol")
    return result


def _judge_work(
    provider: object | None, work: tuple[tuple[JudgeRequest, list[Any]], ...], observed: frozenset[str] = frozenset(),
) -> tuple[str, str]:
    feedback_rows: list[str] = []
    reported: list[str] = []
    confirmed: list[dict] = []
    deadline = time.monotonic() + REVIEW_DEADLINE_SECONDS
    for request, candidates_or_rows in work:
        try:
            result = _judged(provider, request, deadline)
        except LunaProviderFailure as exc:
            raise InterruptedReview(exc, "\n\n".join(feedback_rows), confirmed) from exc
        feedback = _feedback(request, result, candidates_or_rows)
        if not feedback:
            continue
        if request.rule_name in observed:
            reported.append(feedback)
            continue
        feedback_rows.append(feedback)
        if request.review_kind is ReviewKind.DOCUMENT:
            confirmed.append({"feedback": _bounded(feedback), "sources": feedback_sources(result.payload, candidates_or_rows)})
    return "\n\n".join(feedback_rows), "\n\n".join(reported)


def _verdict(feedback: str, reported: str) -> dict:
    """Observed rules report, because the project chose observe."""
    notice = system_message(_bounded(reported)) if reported else {}
    return {**notice, **stop_block(_bounded(feedback))} if feedback else notice


def _observed_rules(payload: object, work: tuple[tuple[JudgeRequest, list[Any]], ...]) -> frozenset[str]:
    """Read per turn, because rule gates live in project config."""
    config = effective_hook_config({}, payloads.cwd(payload) or None)
    manifest = load_manifest()
    return frozenset(
        request.rule_name for request, _sources in work
        if request.review_kind is ReviewKind.PATTERN and not rule_blocks(manifest, request.rule_name, config)
    )


def _preflight(
    payload: object,
    session_id: str,
    turn_id: str,
    state_root: str | Path | None,
) -> tuple[dict[str, Any] | None, int, bool, dict | None]:
    confirmed = pending_feedback(session_id, state_root)
    if confirmed:
        return None, 0, False, stop_block(_bounded(confirmed))
    if provider_cooling(session_id, state_root):
        return None, 0, False, {}
    try:
        previous_failure = _failure_entry(session_id, turn_id, state_root)
    except (OSError, ValueError, TypeError) as exc:
        return None, 0, False, _failure_block(exc)
    attempts = previous_failure.get("attempts", 0) if previous_failure else 0
    attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
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
    observed: frozenset[str] = frozenset(),
) -> dict:
    token, reservation_error = _reserve_review(
        session_id, turn_id, state_root, previous_failure, attempts,
    )
    if reservation_error is not None or token is None:
        return reservation_error or _failure_block("the Luna review reservation could not be acquired", attempts + 1)
    try:
        feedback, reported = _judge_work(provider, work, observed)
    except BaseException:
        _rollback(session_id, turn_id, token, state_root)
        raise
    if _finish_success(session_id, turn_id, token, state_root):
        return _verdict(feedback, reported)
    _rollback(session_id, turn_id, token, state_root)
    reason = "the successful Luna review could not be committed"
    _record_failure(session_id, turn_id, reason, state_root)
    return _failure_block(reason, attempts + 1)


def _outage_response(session_id: str, turn_id: str, state_root: str | Path | None, exc: LunaProviderFailure) -> dict:
    confirmed = exc.confirmed if isinstance(exc, InterruptedReview) else []
    record_provider_outage(session_id, turn_id, _bounded(exc), state_root, feedback=confirmed)
    notice = system_message(_bounded(
        f"ADW Luna review unavailable: {exc}. ADW could not complete this review. "
        "Automatic retries pause for five minutes. Deterministic checks remain active. "
        "Check Codex subscription login and Luna availability."
    ))
    feedback = exc.feedback if isinstance(exc, InterruptedReview) else ""
    return {**notice, **stop_block(_bounded(feedback))} if feedback else notice


def _unresolved_block(session_id: str, turn_id: str, state_root: str | Path | None, exc: Exception) -> dict:
    """Recorded as a failure, because only a successful retry releases it."""
    _record_failure(session_id, turn_id, str(exc), state_root)
    entry = _failure_entry(session_id, turn_id, state_root) or {}
    blocked = _failure_block(exc, entry.get("attempts", 1))
    feedback = exc.feedback if isinstance(exc, InterruptedReview) else ""
    return stop_block(_bounded(f"{blocked['reason']} {feedback}")) if feedback else blocked


def _boundary_open(payload: object) -> bool:
    """Closed on a bad config read, because source text would leave."""
    try:
        return data_boundary_enabled(effective_hook_config({}, payloads.cwd(payload) or None))
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _reviewed(payload: object, session_id: str, turn_id: str, state_root: str | Path | None, provider: object | None) -> dict:
    previous_failure, attempts, _reclaimed, preflight_response = _preflight(
        payload, session_id, turn_id, state_root,
    )
    if preflight_response is not None:
        return preflight_response
    work, empty_reason = _review_work(payload, turn_id, state_root)
    if work is None:
        return _failure_block(previous_failure.get("reason", empty_reason), attempts) if previous_failure else {}
    return _perform_review(
        session_id, turn_id, state_root, previous_failure, attempts, work, provider, _observed_rules(payload, work),
    )


def review(
    payload: object,
    *,
    turn_id: str,
    state_root: str | Path | None = None,
    provider: object | None = None,
) -> dict:
    session_id = payloads.session_id(payload)
    if not session_id or not _boundary_open(payload):
        return {}
    try:
        return _reviewed(payload, session_id, turn_id, state_root, provider)
    except LunaProviderFailure as exc:
        if exc.category not in UNRESOLVED_CATEGORIES:
            return _outage_response(session_id, turn_id, state_root, exc)
        return _unresolved_block(session_id, turn_id, state_root, exc)
    except Exception as exc:
        return _unresolved_block(session_id, turn_id, state_root, exc)
