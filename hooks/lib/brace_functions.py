"""Measure brace-delimited functions, because TypeScript and JavaScript have no ast module to report a function span."""
from __future__ import annotations

import bisect
import re

BRACE_LANGUAGE_EXTS = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
_QUOTES = "'\"`"
_CONTROL_WORDS = frozenset({"if", "for", "while", "switch", "catch", "with", "return", "else", "do", "try", "finally"})
_FUNCTION_HEADER_RE = re.compile(r"\bfunction\b[\s*]*(?P<name>[\w$]*)\s*(?:<[^>]*>)?\s*\([^)]*\)[^=]*$")
_ARROW_HEADER_RE = re.compile(r"=>\s*$")
_ARROW_NAME_RE = re.compile(r"(?P<name>[\w$]+)\s*(?::[^=]+)?=\s*(?:async\b)?")
_METHOD_HEADER_RE = re.compile(
    r"^(?:(?:async|static|get|set|public|private|protected|override|readonly)\s+)*\*?\s*"
    r"(?P<name>[\w$]+)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::[^{]+)?$"
)


def _skip_quoted(text: str, index: int) -> int:
    quote = text[index]
    index += 1
    while index < len(text) and text[index] != quote:
        index += 2 if text[index] == "\\" else 1
    return min(index + 1, len(text))


def _end_after(text: str, needle: str, start: int) -> int:
    end = text.find(needle, start)
    return len(text) if end < 0 else end + len(needle)


def _masked_end(text: str, index: int) -> int | None:
    pair = text[index:index + 2]
    if pair == "//":
        return _end_after(text, "\n", index) - 1 if "\n" in text[index:] else len(text)
    if pair == "/*":
        return _end_after(text, "*/", index + 2)
    return _skip_quoted(text, index) if text[index] in _QUOTES else None


def _masked(text: str) -> str:
    """Blank strings and comments but keep newlines, because a brace inside them does not open a block."""
    out = list(text)
    index = 0
    while index < len(text):
        end = _masked_end(text, index)
        if end is None:
            index += 1
            continue
        out[index:end] = [character if character == "\n" else " " for character in text[index:end]]
        index = end
    return "".join(out)


def _function_name(header: str) -> str | None:
    header = " ".join(header.split())
    if found := _FUNCTION_HEADER_RE.search(header):
        return found.group("name") or "anonymous"
    if _ARROW_HEADER_RE.search(header):
        found = _ARROW_NAME_RE.search(header)
        return found.group("name") if found else "anonymous"
    found = _METHOD_HEADER_RE.match(header)
    if found and found.group("name") not in _CONTROL_WORDS:
        return found.group("name")
    return None


def _header_start(code: str, brace: int) -> int:
    start = max(code.rfind(mark, 0, brace) for mark in ";{}") + 1
    while start < brace and code[start].isspace():
        start += 1
    return start


def _brace_pairs(code: str) -> list[tuple[int, int]]:
    """Drop an unclosed brace, because it has no span to measure."""
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, character in enumerate(code):
        if character == "{":
            stack.append(index)
        elif character == "}" and stack:
            pairs.append((stack.pop(), index))
    return pairs


def block_ends(text: str) -> dict[int, int]:
    """Share the masking, because Rust braces hide in strings too."""
    return dict(_brace_pairs(_masked(text)))


def long_brace_functions(text: str, limit: int) -> list[tuple[int, str, int]]:
    """Count from the header line, because Python measures from the def line and both caps must mean the same span."""
    code = _masked(text)
    newlines = [index for index, character in enumerate(code) if character == "\n"]
    found: list[tuple[int, str, int]] = []
    for opening, closing in _brace_pairs(code):
        start = _header_start(code, opening)
        name = _function_name(code[start:opening])
        first = bisect.bisect_left(newlines, start) + 1
        span = bisect.bisect_left(newlines, closing) + 2 - first
        if name is not None and span > limit:
            found.append((first, name, span))
    return sorted(found)
