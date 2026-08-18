"""Split from scanner.py because sentence and list checks do not depend on comment or docstring rules."""

from __future__ import annotations

import re

try:
    from .comment_rules import _finding
    from .markup import _strip_english_hidden, _strip_inline_code
    from .scan_input import int_setting as _int_setting
except ImportError:
    from comment_rules import _finding
    from markup import _strip_english_hidden, _strip_inline_code
    from scan_input import int_setting as _int_setting

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_REFERENCE_RE = re.compile(r"^\s*\[[^]]+\]:\s+\S")
TABLE_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
WORD_RE = re.compile(r"\b\w+(?:[-']\w+)*\b")


def _next_fence(line: str, fence: str | None) -> tuple[str | None, bool]:
    marker = FENCE_RE.match(line)
    if not marker:
        return fence, False
    marker_kind = marker.group(1)[0]
    if fence is None:
        return marker_kind, True
    return (None if marker_kind == fence else fence), True


def _markdown_prose_lines(text: str):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        fence, is_marker = _next_fence(line, fence)
        if (
            is_marker or fence or line.lstrip().startswith((">", "|"))
            or TABLE_DELIMITER_RE.match(line)
            or LINK_REFERENCE_RE.match(line)
        ):
            yield number, ""
            continue
        yield number, line


def _paragraphs(lines):
    paragraph = []
    for number, line in lines:
        if line.strip() and not LIST_ITEM_RE.match(line):
            paragraph.append((number, line.strip()))
            continue
        if paragraph:
            yield paragraph
            paragraph = []
    if paragraph:
        yield paragraph


def _sentences(paragraph):
    offsets = []
    chunks = []
    size = 0
    for number, line in paragraph:
        offsets.append((size, number))
        chunks.append(line)
        size += len(line) + 1
    prose = " ".join(chunks)
    start = 0
    for boundary in SENTENCE_BREAK_RE.finditer(prose):
        yield _source_line(offsets, start), prose[start:boundary.start()]
        start = boundary.end()
    if prose[start:].strip():
        yield _source_line(offsets, start), prose[start:]


def _source_line(offsets, start: int) -> int:
    line_number = offsets[0][1]
    for offset, number in offsets:
        if offset > start:
            break
        line_number = number
    return line_number


def _long_sentences_in_paragraph(path: str, paragraph, cap: int) -> list[dict]:
    rows = []
    for number, sentence in _sentences(paragraph):
        visible = _strip_inline_code(_strip_english_hidden(sentence))
        if len(WORD_RE.findall(visible)) > cap:
            rows.append(_finding(
                "english", "long_sentence", number,
                "Sentence exceeds the word cap in " + path,
                sentence, "Split it into shorter sentences.",
            ))
    return rows


def _long_sentence_rows(path: str, lines, cap: int) -> list[dict]:
    rows = []
    for paragraph in _paragraphs(lines):
        rows.extend(_long_sentences_in_paragraph(path, paragraph, cap))
    return rows


def _is_list_continuation(line: str, count: int, item_indent: int) -> bool:
    if not count or not line.strip():
        return False
    return len(line) - len(line.lstrip()) > item_indent


def _oversized_list_rows(path: str, lines, cap: int) -> list[dict]:
    rows = []
    count = 0
    start = 0
    first_line = ""
    item_indent = 0
    for number, line in lines:
        is_item = bool(LIST_ITEM_RE.match(line))
        if is_item:
            item_indent = len(line) - len(line.lstrip())
        elif not _is_list_continuation(line, count, item_indent):
            count = 0
            continue
        else:
            continue
        if count == 0:
            start = number
            first_line = line
        count += 1
        if count == cap + 1:
            rows.append(_finding(
                "english", "oversized_list", start,
                "List exceeds the item cap in " + path,
                first_line, "Split the list into smaller ranked groups.",
            ))
    return rows


def _scan_prose_structure(path: str, text: str, config: dict) -> list[dict]:
    lines = list(_markdown_prose_lines(text))
    sentence_cap = _int_setting(config, "sentence_word_cap", "ADW_SENTENCE_WORD_CAP", 40)
    list_cap = _int_setting(config, "list_item_cap", "ADW_LIST_ITEM_CAP", 8)
    findings = _long_sentence_rows(path, lines, sentence_cap)
    findings.extend(_oversized_list_rows(path, lines, list_cap))
    return findings
