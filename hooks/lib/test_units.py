"""Shared test spans, because every Code Check rule must agree."""
from __future__ import annotations

import ast
import bisect
import re
from collections.abc import Iterator
from pathlib import PurePath
from typing import NamedTuple

try:
    from .brace_functions import block_ends
except ImportError:
    from brace_functions import block_ends

PYTHON = "python"
RUST = "rust"
LANGUAGES = {".py": PYTHON, ".rs": RUST}
_RUST_TEST_RE = re.compile(
    r"#\[\s*(?:tokio\s*::\s*)?test\b[^\]]*\]"
    r"(?:\s*#\[[^\]]*\])*\s*"
    r"(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<name>\w+)"
)
_LIFETIME_RE = re.compile(r"'[A-Za-z_]\w*\b(?!')")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class Unit(NamedTuple):
    path: str
    name: str
    start: int
    end: int
    body: str
    language: str


def language_of(path: str) -> str | None:
    """Pick by suffix, because the scanner sees paths first."""
    return LANGUAGES.get(PurePath(path.lower()).suffix)


def extract(path: str, text: str) -> list[Unit]:
    """Return no units, because a broken file has no tests."""
    language = language_of(path)
    if language == PYTHON:
        return _python_units(path, text) if "def test_" in text else []
    if language == RUST:
        return _rust_units(path, text)
    return []


def _python_tests(body: list[ast.stmt]) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in body:
        if isinstance(node, ast.ClassDef):
            yield from _python_tests(node.body)
        if isinstance(node, _FUNCTIONS) and node.name.startswith("test_"):
            yield node


def _python_units(path: str, text: str) -> list[Unit]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    lines = text.splitlines()
    return [
        Unit(path, node.name, node.lineno, node.end_lineno or node.lineno,
             "\n".join(lines[node.lineno - 1:node.end_lineno]), PYTHON)
        for node in _python_tests(tree.body)
    ]


def _without_lifetimes(text: str) -> str:
    """Blank lifetimes, because a lone quote opens a fake string."""
    return _LIFETIME_RE.sub(lambda found: " " * len(found.group(0)), text)


def _rust_units(path: str, text: str) -> list[Unit]:
    ends = block_ends(_without_lifetimes(text))
    openings = sorted(ends)
    newlines = [index for index, character in enumerate(text) if character == "\n"]
    units: list[Unit] = []
    for found in _RUST_TEST_RE.finditer(text):
        position = bisect.bisect_left(openings, found.end())
        if position == len(openings):
            continue
        header = text.rfind("\n", 0, found.start("name")) + 1
        closing = ends[openings[position]]
        start = bisect.bisect_left(newlines, header) + 1
        end = bisect.bisect_left(newlines, closing) + 1
        units.append(Unit(path, found.group("name"), start, end, text[header:closing + 1], RUST))
    return units
