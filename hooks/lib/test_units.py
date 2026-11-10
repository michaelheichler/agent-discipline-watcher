"""Shared test spans, because every Code Check rule must agree."""
from __future__ import annotations

import ast
import bisect
import re
from collections.abc import Iterator
from pathlib import PurePath
from typing import NamedTuple

try:
    from .brace_functions import block_ends, masked_code
except ImportError:
    from brace_functions import block_ends, masked_code

PYTHON = "python"
RUST = "rust"
JAVASCRIPT = "javascript"
LANGUAGES = {".py": PYTHON, ".rs": RUST, **dict.fromkeys((".ts", ".tsx", ".js", ".jsx"), JAVASCRIPT)}
_JS_PATH_RE = re.compile(r"\.(?:test|spec)\.(?:[jt]sx?)$", re.IGNORECASE)
_JS_TEST_RE = re.compile(r"(?<![\w$.])(?P<kind>test|it|describe)(?:\.(?:only|skip|todo))?\s*\(")
_JS_CALLBACK_RE = re.compile(r"=>\s*\{|\bfunction\s*\w*\s*\([^)]*\)\s*\{")
_JS_ASSERT_RE = re.compile(r"(?<![\w$.])(?:(?:expect|assert)\s*\(|assert\s*\.\s*\w+\s*\()")
_RUST_TEST_RE = re.compile(
    r"#\[\s*(?:tokio\s*::\s*)?test\b[^\]]*\]"
    r"(?:\s*#\[[^\]]*\])*\s*"
    r"(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<name>\w+)"
)
_CFG_TEST_RE = re.compile(r"#\[\s*cfg\s*\(\s*test\s*\)\s*\]")
_LIFETIME_RE = re.compile(r"'[A-Za-z_]\w*\b(?!')")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class Unit(NamedTuple):
    path: str
    name: str
    start: int
    end: int
    body: str
    language: str
    attributes: str = ""


def language_of(path: str) -> str | None:
    """Pick by suffix, because the scanner sees paths first."""
    language = LANGUAGES.get(PurePath(path.lower()).suffix)
    if language == JAVASCRIPT and not _JS_PATH_RE.search(path):
        return None
    return language


def extract(path: str, text: str) -> list[Unit]:
    """Return no units, because a broken file has no tests."""
    language = language_of(path)
    if language == PYTHON:
        return _python_units(path, text) if "def test_" in text else []
    if language == RUST:
        return _rust_units(path, text)
    if language == JAVASCRIPT:
        return _javascript_units(path, text)
    return []


def _call_end(code: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(code)):
        if code[index] == "(":
            depth += 1
        elif code[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return opening


def _javascript_units(path: str, text: str) -> list[Unit]:
    code = masked_code(text, javascript=True)
    ends = block_ends(text, javascript=True)
    units = []
    for found in _JS_TEST_RE.finditer(code):
        end = _call_end(code, found.end() - 1)
        callback = _JS_CALLBACK_RE.search(code, found.end(), end)
        if callback is None or found.group("kind") == "describe":
            continue
        closing = ends.get(callback.end() - 1)
        if closing is None:
            continue
        header = text[found.start():callback.start()].split(",", 1)[0].strip()
        start = code.count("\n", 0, found.start()) + 1
        stop = code.count("\n", 0, closing) + 1
        units.append(Unit(path, header, start, stop, text[found.start():closing + 1], JAVASCRIPT))
    return units


def _javascript_expression_end(code: str, start: int) -> int:
    stack = []
    for index in range(start, len(code)):
        char = code[index]
        if not stack and char in ";,)]}":
            return index
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            stack.pop()
    return len(code)


def javascript_scope(unit: Unit) -> str:
    """Because helpers own their branches, mask nested callback scopes."""
    code = masked_code(unit.body, javascript=True)
    ends = block_ends(unit.body, javascript=True)
    callbacks = list(_JS_CALLBACK_RE.finditer(code))
    out = list(code)
    for callback in callbacks[1:]:
        opening = callback.end() - 1
        closing = ends.get(opening)
        if closing is not None:
            out[callback.start():closing + 1] = ["\n" if char == "\n" else " "
                                               for char in code[callback.start():closing + 1]]
    for arrow in re.finditer(r"=>\s*(?!\s*\{)", code):
        end = _javascript_expression_end(code, arrow.end())
        out[arrow.start():end] = ["\n" if char == "\n" else " " for char in code[arrow.start():end]]
    return "".join(out)


def javascript_assertions(code: str) -> list[int]:
    return [found.start() for found in _JS_ASSERT_RE.finditer(code)]


def _python_tests(
    body: list[ast.stmt], lines: list[str], outer: str = "",
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """Carry class decorators, because a skip there hides each test."""
    for node in body:
        if isinstance(node, ast.ClassDef):
            yield from _python_tests(node.body, lines, outer + _decorator_text(node, lines))
        if isinstance(node, _FUNCTIONS) and node.name.startswith("test_"):
            yield node, outer + _decorator_text(node, lines)


def _decorator_text(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> str:
    if not node.decorator_list:
        return ""
    first = min(decorator.lineno for decorator in node.decorator_list)
    return "".join(line + "\n" for line in lines[first - 1:node.lineno - 1])


def _python_units(path: str, text: str) -> list[Unit]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    lines = text.splitlines()
    return [
        Unit(path, node.name, node.lineno, node.end_lineno or node.lineno,
             "\n".join(lines[node.lineno - 1:node.end_lineno]), PYTHON, decorators)
        for node, decorators in _python_tests(tree.body, lines)
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
        attributes = text[_attributes_start(text, found.start()):header]
        units.append(Unit(path, found.group("name"), start, end, text[header:closing + 1], RUST, attributes))
    return units


def _attributes_start(text: str, test_attribute: int) -> int:
    """Walk up, because #[ignore] may sit above #[test]."""
    start = text.rfind("\n", 0, test_attribute) + 1
    while start:
        above = text.rfind("\n", 0, start - 1) + 1
        if not text[above:start].lstrip().startswith("#["):
            break
        start = above
    return start


def rust_cfg_test_blocks(text: str) -> list[str]:
    """Whole items, because a cfg(test) mod holds helpers too."""
    ends = block_ends(_without_lifetimes(text))
    openings = sorted(ends)
    blocks: list[str] = []
    for found in _CFG_TEST_RE.finditer(text):
        position = bisect.bisect_left(openings, found.end())
        stop = text.find(";", found.end())
        if position < len(openings) and not 0 <= stop < openings[position]:
            blocks.append(text[found.start():ends[openings[position]] + 1])
        else:
            blocks.append(text[found.start():stop + 1 if stop >= 0 else len(text)])
    return blocks
