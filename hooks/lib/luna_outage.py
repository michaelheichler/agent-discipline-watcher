"""Split from the Luna handlers, because an outage must neither block a Stop nor spend a retry on every turn."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from . import journal, payloads, reporting, turn_retry
from .hookio import advise, system_message
from .luna_feedback import LUNA, bounded

LEDGER_HOOK = "claude_luna"
DROPPED_RULE = "review_dropped"
MAX_NAMED_ROWS = 5
OUTAGE_CATEGORIES = frozenset({"authentication", "availability", "configuration", "provider", "timeout"})


def is_outage(error: Exception) -> bool:
    """Because a malformed verdict says nothing about the next call, it starts no cooldown."""
    return getattr(error, "category", None) in OUTAGE_CATEGORIES or isinstance(error, OSError)


def retryable(payload: object, rows: list[dict[str, Any]], root: str | Path | None) -> list[dict[str, Any]]:
    try:
        counts = turn_retry.attempts(payloads.session_id(payload), root)
    except (OSError, ValueError, TypeError):
        return rows
    return [row for row in rows if counts.get(journal._reviewed_key(row), 0) < turn_retry.MAX_REVIEW_ATTEMPTS]


def cooling(payload: object, root: str | Path | None) -> bool:
    try:
        return turn_retry.cli_cooldown(payloads.session_id(payload), root) is not None
    except (OSError, ValueError, TypeError):
        return False


def cooldown_notice(payload: object, root: str | Path | None) -> dict:
    """Visible, because a silent cooldown reads like a clean review."""
    try:
        cooldown = turn_retry.cli_cooldown(payloads.session_id(payload), root)
    except (OSError, ValueError, TypeError):
        return {}
    if cooldown is None:
        return {}
    reason, retry_after = cooldown
    until = time.strftime("%H:%M:%S", time.localtime(retry_after))
    return system_message(bounded(
        f"ADW {LUNA} review did not run this turn: {reason or 'the Codex runtime failed'}. "
        f"ADW skips the review until {until}, and the queued findings stay queued."
    ))


def _row_names(rows: list[dict[str, Any]]) -> str:
    names = []
    for row in rows:
        name = Path(str(row.get("path") or "")).name or "an unnamed file"
        line = row.get("line")
        names.append(f"{name}:{line}" if row.get("role") == "pattern" and type(line) is int else name)
    unique = list(dict.fromkeys(names))
    shown = ", ".join(unique[:MAX_NAMED_ROWS])
    return f"{shown} and {len(unique) - MAX_NAMED_ROWS} more" if len(unique) > MAX_NAMED_ROWS else shown


def _record_dropped(payload: object, rows: list[dict[str, Any]], ledger_root: str | Path | None) -> None:
    for row in rows:
        reporting.record_decision(
            session_id=payloads.session_id(payload), hook=LEDGER_HOOK, event="Stop", family="", rule=DROPPED_RULE,
            path=str(row.get("path") or ""), tool_use_id="", outcome="release", duration_ms=0,
            turn_id=str(row.get("turn_id") or ""), root=ledger_root,
        )


def _exhausted(
    payload: object, rows: list[dict[str, Any]], root: str | Path | None, ledger_root: str | Path | None,
) -> list[dict[str, Any]]:
    """Counted per row, so a row that never gets a verdict stops resending."""
    try:
        keys = [journal._reviewed_key(row) for row in rows]
        exhausted = turn_retry.exhausted_reviews(payloads.session_id(payload), keys, root)
    except (OSError, ValueError, TypeError):
        return []
    dropped = [row for row in rows if journal._reviewed_key(row) in exhausted]
    if dropped:
        try:
            journal.mark_reviewed(payloads.session_id(payload), dropped, state_root=root)
        except (OSError, RuntimeError, TypeError, ValueError):
            return dropped
        _record_dropped(payload, dropped, ledger_root)
    return dropped


def failed_stop(
    payload: object, rows: list[dict[str, Any]], reason: str, root: str | Path | None, ledger_root: str | Path | None,
    *, cooldown: bool = True,
) -> dict:
    """Advice only, because blocking every Stop during a provider outage would trap the agent."""
    lead = f"ADW {LUNA} review did not run this turn: {reason}."
    try:
        if cooldown:
            turn_retry.record_cli_outage(payloads.session_id(payload), reason, root)
    except (OSError, ValueError, TypeError):
        return system_message(bounded(f"{lead} Its findings stay queued."))
    dropped = _exhausted(payload, rows, root, ledger_root)
    if not dropped:
        return system_message(bounded(f"{lead} Its findings stay queued."))
    rest = " The rest stay queued." if len(dropped) < len(rows) else ""
    summary = (
        f"It dropped {len(dropped)} queued findings unreviewed after {turn_retry.MAX_REVIEW_ATTEMPTS} "
        f"attempts without a verdict: {_row_names(dropped)}."
    )
    return advise(bounded(f"{lead} {summary}{rest}"), "Stop")


def record_outage(payload: object, reason: str, root: str | Path | None) -> None:
    """Best effort, because a lost mark only costs one more try."""
    try:
        turn_retry.record_cli_outage(payloads.session_id(payload), reason, root)
    except (OSError, ValueError, TypeError):
        pass
