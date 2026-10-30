"""Separate from comment_rules because these lines pass every deterministic check and are handed to a judge instead of blocked."""
from __future__ import annotations
import ast
from pathlib import PurePath

try:
    from .comment_rules import (
        _comment_body_lines,
        _docstring_scopes,
        _has_strong_why_marker,
        _normalize_block_comments,
        _scope_docstring,
        opens_with_narration,
    )
    from .judge import Candidate
    from .markup import COMMENTABLE_EXTS, MIXED_LANGUAGE_EXTS, CommentSource, comment_scan_source, extract_regions
except ImportError:
    from comment_rules import (
        _comment_body_lines,
        _docstring_scopes,
        _has_strong_why_marker,
        _normalize_block_comments,
        _scope_docstring,
        opens_with_narration,
    )
    from judge import Candidate
    from markup import COMMENTABLE_EXTS, MIXED_LANGUAGE_EXTS, CommentSource, comment_scan_source, extract_regions


def _is_candidate(text: str) -> bool:
    """Only a line that survives the deterministic pass needs a judge, because one without a why marker already blocks."""
    return opens_with_narration(text) and _has_strong_why_marker(text)


def _comment_candidates(path: str, text: str) -> list[Candidate]:
    """Masked first, because a comment marker inside a string is no comment."""
    source = CommentSource(path, text, extract_regions(path, text), PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS)
    comment_text = _normalize_block_comments(comment_scan_source(source), path)
    return [
        Candidate(path, number, comment)
        for number, _line, comment in _comment_body_lines(comment_text)
        if _is_candidate(comment)
    ]


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


def _python_comment_candidates(path: str, text: str) -> list[Candidate]:
    return [
        Candidate(path, number, comment)
        for number, _line, comment in _comment_body_lines(text)
        if _is_candidate(comment)
    ]


def candidates(path: str, text: str) -> tuple[Candidate, ...]:
    suffix = PurePath(path.lower()).suffix
    if suffix != ".py":
        return tuple(_comment_candidates(path, text)) if suffix in COMMENTABLE_EXTS else ()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()
    found = _docstring_candidates(path, tree)
    found.extend(_python_comment_candidates(path, text))
    return tuple(sorted(found, key=lambda item: item.line))
