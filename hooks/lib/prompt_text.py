"""Kept in its own module so that the firewall stays pure text, free of config or payload access."""

from __future__ import annotations

import re
import unicodedata

_QUOTED_RE = re.compile(
    r"(?<!\w)\"(?:\\.|[^\"\\\n])*\"|"
    r"(?<!\w)'(?:\\.|[^'\\\n])*'|"
    r"(?<!\w)“[^”\n]*”|(?<!\w)‘[^’\n]*’"
)
_MIN_FENCE_WIDTH = 3
_MAX_FENCE_INDENT = 3
_AT_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_AT_SEGMENT = _AT_ALNUM | frozenset("_+~.-")
_AT_BOUNDARY_EXCLUDED = _AT_ALNUM | frozenset("_@./+~-")
_AT_TERMINATORS = frozenset(
    " \t\n\r\v\f,;:!?()[]{}\"'\u201c\u201d\u2018\u2019\u2014\u2013\u2026\u00bb"
)


def _mask_quoted(text: str) -> str:
    return _QUOTED_RE.sub(lambda match: " " * len(match.group(0)), text)


def _fence_body(line: str) -> str:
    indent = len(line) - len(line.lstrip(" "))
    return line[indent:] if indent <= _MAX_FENCE_INDENT else ""


def _fence_opener_width(line: str) -> int:
    body = _fence_body(line)
    width = len(body) - len(body.lstrip("`"))
    if width < _MIN_FENCE_WIDTH:
        return 0
    return width if "`" not in body[width:] else 0


def _is_fence_closer(line: str, width: int) -> bool:
    body = _fence_body(line)
    backticks = len(body) - len(body.lstrip("`"))
    return backticks >= width and not body[backticks:].strip(" \t\r\n")


def _mask_span(masked: list[str], start: int, end: int) -> None:
    for position in range(start, end):
        if masked[position] != "\n":
            masked[position] = " "


def _fenced_region_extent(
    lines: list[str], opener_index: int, width: int,
) -> tuple[int, int]:
    length = len(lines[opener_index])
    index = opener_index + 1
    while index < len(lines):
        length += len(lines[index])
        closer = _is_fence_closer(lines[index], width)
        index += 1
        if closer:
            break
    return length, index


def _mask_fenced(text: str) -> str:
    if "```" not in text:
        return text
    lines = text.splitlines(keepends=True)
    offsets = [0] * len(lines)
    for index in range(1, len(lines)):
        offsets[index] = offsets[index - 1] + len(lines[index - 1])
    masked = list(text)
    index = 0
    while index < len(lines):
        width = _fence_opener_width(lines[index])
        if not width:
            index += 1
            continue
        start = offsets[index]
        length, index = _fenced_region_extent(lines, index, width)
        _mask_span(masked, start, start + length)
    return "".join(masked)


def _find_backtick_run(text: str, start: int, width: int) -> int:
    index = start
    while index < len(text):
        if text[index] != "`":
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] == "`":
            end += 1
        if end - index == width:
            return index
        index = end
    return -1


def _mask_code_width(text: str, width: int) -> str:
    if "`" * width not in text:
        return text
    masked = list(text)
    start = _find_backtick_run(text, 0, width)
    while start != -1:
        close = _find_backtick_run(text, start + width, width)
        if close == -1:
            break
        _mask_span(masked, start, close + width)
        start = _find_backtick_run(text, close + width, width)
    return "".join(masked)


def _mask_inline_code(text: str) -> str:
    return _mask_code_width(_mask_code_width(text, 2), 1)


def mask_examples(text: str) -> str:
    return _mask_quoted(_mask_inline_code(_mask_fenced(text)))


def _is_combining_mark(char: str) -> bool:
    return bool(char) and unicodedata.category(char).startswith("M")


def _file_token_end(text: str, at: int) -> int:
    end = at + 1
    has_alnum = False
    segment_open = False
    for index in range(at + 1, len(text) + 1):
        char = text[index] if index < len(text) else ""
        if char in _AT_SEGMENT or char.isalnum() or _is_combining_mark(char):
            has_alnum = has_alnum or char.isalnum()
            segment_open = True
            end = index + 1
            continue
        if char == "/" and (segment_open or index == at + 1):
            segment_open = False
            continue
        break
    if end == at + 1 or not has_alnum:
        return -1
    return end if end == len(text) or _is_token_terminator(text[end]) else -1


def _is_token_terminator(char: str) -> bool:
    return char in _AT_TERMINATORS or char.isspace() or char == "`"


def _is_token_boundary(char: str) -> bool:
    return (
        char in _AT_BOUNDARY_EXCLUDED
        or char.isalnum()
        or unicodedata.category(char).startswith("M")
    )


def has_file_token(text: str) -> bool:
    at = text.find("@")
    while at != -1:
        if (at == 0 or not _is_token_boundary(text[at - 1])) and (
            _file_token_end(text, at) != -1
        ):
            return True
        at = text.find("@", at + 1)
    return False
