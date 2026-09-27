"""Shared because two hosts reading one Luna result must not diverge on the wording."""
from __future__ import annotations

from typing import Any

from . import reporting
from .finding_output import ReviewNote, format_row, review_row

MAX_FEEDBACK_CHARS = 900
MAX_LISTED_ROWS = 5
COMMENT_LEAD = "ADW Luna comment review:"
DOCUMENT_LEAD = "ADW Luna document review:"
PATTERN_LEAD = "ADW Luna pattern review:"
COMMENT_ACTION = "Rewrite the comment to say why the code exists, or delete it."
DOCUMENT_ACTION = "Fix the named document issue."


def bounded(value: object) -> str:
    """Collapse and cut because an unbounded reason would flood the surface that shows it."""
    return " ".join(str(value).split())[:MAX_FEEDBACK_CHARS]


def _listing(lead: str, rows: list[str]) -> str:
    """Write the full report when rows are cut, because the reader needs a path to every finding."""
    listed = rows[:MAX_LISTED_ROWS]
    body = "\n".join([lead, *(f"{number}. {row}" for number, row in enumerate(listed, 1))])
    extra = len(rows) - len(listed)
    if not extra and len(body) <= MAX_FEEDBACK_CHARS:
        return body
    report = reporting.write_full_report([{"message": row} for row in rows])
    tail = f"{extra} more findings: {report}" if extra else f"Full report: {report}"
    return body[:max(MAX_FEEDBACK_CHARS - len(tail) - 1, 0)] + "\n" + tail


def _verdicts(result: Any, found: tuple[Any, ...], verdict: str) -> list[tuple[Any, dict]]:
    """Drop a row whose index misses because a stray index would name the wrong line."""
    rows = result.payload.get("items")
    if not isinstance(rows, list):
        return []
    matched = []
    for row in rows:
        if not isinstance(row, dict) or row.get("verdict") != verdict:
            continue
        index = row.get("index")
        if type(index) is int and 0 <= index < len(found):
            matched.append((found[index], row))
    return matched


def _item_rows(result: Any, found: tuple[Any, ...], verdict: str, action: str) -> list[str]:
    return [
        review_row(ReviewNote(
            f"{candidate.path}:{candidate.line}", bounded(candidate.text),
            bounded(row.get("reason", "The judge named no reason.")), action,
        ))
        for candidate, row in _verdicts(result, found, verdict)
    ]


def _finding_rows(result: Any, found: tuple[Any, ...], rule: str, action: str) -> list[str]:
    """Titled like a rule finding, because the reader acts on both."""
    return [
        format_row({
            "path": candidate.path, "line": candidate.line, "rule": rule,
            "match": candidate.text, "action": action,
        })
        for candidate, _row in _verdicts(result, found, "violating")
    ]


def comment_feedback(result: Any, found: tuple[Any, ...]) -> str:
    feedback = _item_rows(result, found, "describes_code", COMMENT_ACTION)
    return _listing(COMMENT_LEAD, feedback) if feedback else ""


def pattern_feedback(result: Any, found: tuple[Any, ...], action: str, rule: str = "") -> str:
    """Rule optional, because Codex does not pass one yet."""
    if rule:
        feedback = _finding_rows(result, found, rule, bounded(action))
    else:
        feedback = _item_rows(result, found, "violating", bounded(action))
    return _listing(PATTERN_LEAD, feedback) if feedback else ""


def _quote_location(quote: str, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        source = str(row.get("source_context", "")) if isinstance(row, dict) else ""
        if quote and quote in source:
            return f"{row.get('path', '')}:{source[:source.index(quote)].count(chr(10)) + 1}"
    return "document"


def document_feedback(result: Any, rows: list[dict[str, Any]]) -> str:
    """Require a named problem because a note without one gives the writer nothing to act on."""
    notes = result.payload.get("notes")
    if not isinstance(notes, list):
        return ""
    feedback = []
    for row in notes:
        if not isinstance(row, dict) or not row.get("problem"):
            continue
        quote = bounded(row.get("quote", ""))
        location = _quote_location(str(row.get("quote", "")), rows)
        note = ReviewNote(location, quote, bounded(row["problem"]), bounded(row.get("fix", DOCUMENT_ACTION)))
        feedback.append(review_row(note))
    return _listing(DOCUMENT_LEAD, feedback) if feedback else ""
