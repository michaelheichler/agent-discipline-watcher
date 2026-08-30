"""Shared because two hosts reading one Luna result must not diverge on the wording."""
from __future__ import annotations

from typing import Any

MAX_FEEDBACK_CHARS = 900


def bounded(value: object) -> str:
    """Collapse and cut because an unbounded reason would flood the surface that shows it."""
    return " ".join(str(value).split())[:MAX_FEEDBACK_CHARS]


def comment_feedback(result: Any, found: tuple[Any, ...]) -> str:
    """Drop a row whose index misses because a stray index would name the wrong line."""
    rows = result.payload.get("items")
    if not isinstance(rows, list):
        return ""
    feedback = []
    for row in rows:
        if not isinstance(row, dict) or row.get("verdict") != "describes_code":
            continue
        index = row.get("index")
        if type(index) is not int or not 0 <= index < len(found):
            continue
        feedback.append(f"{found[index].path}:{found[index].line}: {bounded(row.get('reason', 'Rewrite this comment.'))}")
    return bounded("ADW Luna comment review: " + " | ".join(feedback)) if feedback else ""


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
        problem = bounded(row.get("problem", ""))
        fix = bounded(row.get("fix", "Fix the named document issue."))
        feedback.append(f"{quote}: {problem} Fix: {fix}")
    return bounded("ADW Luna document review: " + " | ".join(feedback)) if feedback else ""
