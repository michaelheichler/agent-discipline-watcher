"""Separate from comment_rules because these lines pass every deterministic check and are handed to a judge instead of blocked."""
from __future__ import annotations

import ast

try:
    from .comment_rules import (
        _comment_body_lines,
        _docstring_scopes,
        _has_strong_why_marker,
        _scope_docstring,
        opens_with_narration,
    )
    from .judge import Candidate
except ImportError:
    from comment_rules import (
        _comment_body_lines,
        _docstring_scopes,
        _has_strong_why_marker,
        _scope_docstring,
        opens_with_narration,
    )
    from judge import Candidate


def _is_candidate(text: str) -> bool:
    """Only a line that survives the deterministic pass needs a judge, because one without a why marker already blocks."""
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
