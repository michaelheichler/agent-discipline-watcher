"""Kept in the core because a turn recorded under one host still needs clearing when the marker is gone."""
from __future__ import annotations

from pathlib import Path
import time

try:
    from . import journal, session_state
except ImportError:
    import journal
    import session_state


RETRY_KEY = "codex_luna_retry_turn"
FAILED_KEY = "codex_luna_failed_reviews"
OUTAGE_KEY = "codex_luna_provider_outage"
PROVIDER_COOLDOWN_SECONDS = 300


def failure_entry(session_id: str, turn_id: str, state_root: str | Path | None) -> dict | None:
    rows = session_state.read_state(session_id, state_root).get(FAILED_KEY)
    if not isinstance(rows, list):
        return None
    key = turn_id or "<initial>"
    return next((row for row in rows if isinstance(row, dict) and row.get("turn_id") == key), None)


def record_failure(
    session_id: str, turn_id: str, reason: str, state_root: str | Path | None,
) -> None:
    key = turn_id or "<initial>"

    def update(state: dict) -> dict:
        rows = [row for row in state.get(FAILED_KEY, []) if isinstance(row, dict)]
        previous = next((row for row in rows if row.get("turn_id") == key), None)
        attempts = previous.get("attempts", 0) if isinstance(previous, dict) else 0
        attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
        rows = [row for row in rows if row.get("turn_id") != key]
        rows.append({"turn_id": key, "attempts": attempts + 1, "reason": reason[:900]})
        return {**state, FAILED_KEY: rows[-64:], RETRY_KEY: key}

    session_state.update_state(session_id, update, state_root)


def provider_cooling(session_id: str, state_root: str | Path | None) -> bool:
    outage = session_state.read_state(session_id, state_root).get(OUTAGE_KEY)
    retry_after = outage.get("retry_after") if isinstance(outage, dict) else None
    return type(retry_after) in (int, float) and retry_after > time.time()


def _source_retains_feedback(source: dict) -> bool:
    path, digest = source.get("path"), source.get("content_hash")
    if not isinstance(path, str) or not path or not isinstance(digest, str) or not digest:
        return True
    outcome = journal._read_content(Path(path))
    return outcome.status == "transient" or (outcome.value is not None and outcome.value[0] == digest)


def pending_feedback(session_id: str, state_root: str | Path | None) -> str:
    outage = session_state.read_state(session_id, state_root).get(OUTAGE_KEY)
    entries = outage.get("feedback", []) if isinstance(outage, dict) else []
    retained = []
    for entry in entries:
        sources = entry.get("sources", [])
        if not sources or any(_source_retains_feedback(source) for source in sources):
            retained.append(entry["feedback"])
    return "\n\n".join(dict.fromkeys(retained))


def record_provider_outage(
    session_id: str, turn_id: str, reason: str, state_root: str | Path | None,
    *, feedback: list[dict] | None = None,
) -> None:
    key = turn_id or "<initial>"

    def update(state: dict) -> dict:
        updated = {**state, OUTAGE_KEY: {
            "turn_id": turn_id,
            "reason": reason[:900],
            "retry_after": time.time() + PROVIDER_COOLDOWN_SECONDS,
            "feedback": feedback or [],
        }}
        failures = state.get(FAILED_KEY)
        if isinstance(failures, list):
            updated[FAILED_KEY] = [
                row for row in failures if not (isinstance(row, dict) and row.get("turn_id") == key)
            ]
        if state.get(RETRY_KEY) == key:
            updated.pop(RETRY_KEY, None)
        return updated

    session_state.update_state(session_id, update, state_root)


def retry_turn_id(session_id: str, state_root: str | Path | None) -> str:
    """Answer with an empty string on a broken read because a missing retry must not block the turn."""
    try:
        value = session_state.read_state(session_id, state_root).get(RETRY_KEY)
    except (OSError, ValueError, TypeError):
        return ""
    return value if isinstance(value, str) and value else ""


def clear_retry_identity(session_id: str, state_root: str | Path | None) -> None:
    """Swallow a failure here because session end must release state rather than raise on the way out."""
    def update(state: dict) -> dict:
        return {key: value for key, value in state.items() if key != RETRY_KEY}

    try:
        session_state.update_state(session_id, update, state_root)
    except (OSError, ValueError, TypeError):
        pass
