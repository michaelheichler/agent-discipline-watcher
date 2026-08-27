"""Separate from comment_rules because these lines pass every deterministic check and are handed to a judge instead of blocked."""
from __future__ import annotations

import ast
import re

try:
    from .comment_rules import _comment_body_lines, _docstring_scopes, _has_strong_why_marker, _scope_docstring
    from .judge import Candidate
except ImportError:
    from comment_rules import _comment_body_lines, _docstring_scopes, _has_strong_why_marker, _scope_docstring
    from judge import Candidate

# Third person and gerund only, because a bare participle like "Set to 1.5 because" states a decision while "Sets the cap" describes the code.
NARRATION_OPENER_RE = re.compile(
    r"^(?:[A-Za-z]+(?:s|ing))\s+"
    r"(?:the|a|an|it|this|to|into|out|off|from|by|on|as|every|each|one|two|all)\b",
)
# WHY: These open a clause about a state or a circumstance, so the opener test would read them as mechanics they never describe.
OPENER_EXCEPTIONS = frozenset({
    "nothing", "during", "using", "pending", "missing", "according", "everything", "anything",
})


def opens_with_narration(text: str) -> bool:
    match = NARRATION_OPENER_RE.match(text.strip())
    if match is None:
        return False
    return match.group(0).split()[0].lower() not in OPENER_EXCEPTIONS


def _is_candidate(text: str) -> bool:
    """Requires the why marker because a line without one is already blocked, and only the lines that pass need a judge."""
    return opens_with_narration(text) and _has_strong_why_marker(text)


def _docstring_candidates(path: str, tree: ast.AST) -> list[Candidate]:
    found = []
    for scope in _docstring_scopes(tree):
        hit = _scope_docstring(scope)
        if hit is None:
            continue
        first = hit[1].strip().splitlines()[0] if hit[1].strip() else ""
        if _is_candidate(first):
            found.append(Candidate(path, hit[0], first))
    return found


def _comment_candidates(path: str, text: str) -> list[Candidate]:
    return [
        Candidate(path, number, comment)
        for number, _line, comment in _comment_body_lines(text)
        if _is_candidate(comment)
    ]


def candidates(path: str, text: str) -> tuple[Candidate, ...]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()
    found = _docstring_candidates(path, tree)
    found.extend(_comment_candidates(path, text))
    return tuple(sorted(found, key=lambda item: item.line))
