"""Split from scanner.py because sentence and list checks do not depend on comment or docstring rules."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterator
from functools import lru_cache
from pathlib import PurePath
from statistics import fmean, pstdev
from typing import NamedTuple

try:
    from .findings import finding_row
    from .findings import spanning
    from .markup import MIXED_LANGUAGE_EXTS, _strip_english_hidden, _strip_inline_code, markdown_lines
    from .scan_input import int_setting as _int_setting
    from .triad_items import ListRun, forced_triad
except ImportError:
    from findings import finding_row
    from findings import spanning
    from markup import MIXED_LANGUAGE_EXTS, _strip_english_hidden, _strip_inline_code, markdown_lines
    from scan_input import int_setting as _int_setting
    from triad_items import ListRun, forced_triad

LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
WORD_RE = re.compile(r"\b\w+(?:[-']\w+)*\b")
THREE_ITEM_RE = re.compile(
    r"\b(?:[a-z]+\s+){0,2}[a-z]+,\s+(?!(?:which|we|i|it|they|he|she|because)\b)"
    r"(?:[a-z]+\s+){0,2}[a-z]+,\s+(?:and|or)\s+"
    r"(?!(?:which|we|i|it|they|he|she|because)\b)(?:[a-z]+\s+){0,2}[a-z]+(?=[.!?)]|$)",
    re.IGNORECASE,
)
MIN_VARIANCE_SENTENCES = 4
# Because 0.32 flagged 33.85% of 709 real paragraphs, use their measured p05.
SENTENCE_VARIATION_LIMIT = 0.16
RHYTHM_LIMITATIONS = {
    "low_sentence_variance": (
        "The threshold is the p05 of 709 real paragraphs, and the essay corpus holds one "
        "truncated paragraph per row, so it yields no true positive to measure against."
    ),
}
MIN_ENDING_SENTENCES = 2
MIN_ENDING_PARAGRAPHS = 3
# Because 30700 human endings give p25 0.7018, use evals/paragraph_endings.json.
PUNCHY_ENDING_RATIO = 0.7018
# Because p95 of 4570 human documents flags 3.15%, use that corpus threshold.
PUNCHY_SHARE_LIMIT = 0.6667
ProseLine = tuple[int, str]
Paragraph = list[ProseLine]


class _ListSpan(NamedTuple):
    start: int
    first_line: str
    last: int
    count: int


class SentenceSpan(NamedTuple):
    first: int
    start: int
    last: int
    end: int
    text: str


def _next_frontmatter(line: str, number: int, active: bool) -> bool:
    if not active:
        return False
    return number == 1 or line.strip() not in ("---", "...")


@lru_cache(maxsize=2)
def _markdown_prose_lines(text: str) -> tuple[tuple[int, str], ...]:
    frontmatter = text.startswith("---\n")
    result = []
    for block in markdown_lines(text):
        number, line = block.number, block.content
        in_frontmatter = frontmatter
        frontmatter = _next_frontmatter(line, number, frontmatter)
        hidden = in_frontmatter or block.hidden or block.prose_boundary
        result.append((number, "" if hidden else line))
    return tuple(result)


def _paragraphs(lines) -> Iterator[list[tuple[int, str]]]:
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


def _sentences(paragraph) -> Iterator[tuple[int, str]]:
    for span in sentence_spans(paragraph):
        yield span.first, span.text


def sentence_spans(paragraph: Paragraph) -> Iterator[SentenceSpan]:
    """Columns index the stripped paragraph lines, because provenance places a match by them."""
    offsets = []
    chunks = []
    size = 0
    for number, line in paragraph:
        offsets.append((size, number))
        chunks.append(line)
        size += len(line) + 1
    prose = " ".join(chunks)
    for start, end in _sentence_bounds(prose):
        first, column = _position(offsets, start)
        last, stop = _position(offsets, max(end - 1, start))
        yield SentenceSpan(first, column, last, stop + 1, prose[start:end])


def _sentence_bounds(prose: str) -> Iterator[tuple[int, int]]:
    start = 0
    for boundary in SENTENCE_BREAK_RE.finditer(prose):
        yield start, boundary.start()
        start = boundary.end()
    if prose[start:].strip():
        yield start, len(prose)


def _position(offsets: list[tuple[int, int]], start: int) -> tuple[int, int]:
    """Bisected, because a scan from the first line for every sentence made a long paragraph quadratic."""
    size, number = offsets[max(bisect_right(offsets, (start, float("inf"))) - 1, 0)]
    return number, start - size


def _source_line(offsets: list[tuple[int, int]], start: int) -> int:
    return _position(offsets, start)[0]


def _sentence_word_counts(paragraph: Paragraph) -> list[int]:
    counts = []
    for _number, sentence in _sentences(paragraph):
        visible = _strip_inline_code(_strip_english_hidden(sentence))
        count = len(WORD_RE.findall(visible))
        if count:
            counts.append(count)
    return counts


def _low_variance_rows(path: str, paragraphs: list[Paragraph]) -> list[dict]:
    rows = []
    for paragraph in paragraphs:
        counts = _sentence_word_counts(paragraph)
        if len(counts) < MIN_VARIANCE_SENTENCES:
            continue
        variation = pstdev(counts) / fmean(counts)
        if variation >= SENTENCE_VARIATION_LIMIT:
            continue
        number, first_line = paragraph[0]
        rows.append(spanning(finding_row(
            "english", "low_sentence_variance", number,
            "Paragraph has uniform sentence lengths in " + path,
            first_line, "Vary the sentence lengths in this paragraph.",
        ), paragraph[-1][0]))
    return rows


def _ending_ratio(paragraph: Paragraph) -> float | None:
    """Because sentence length differs by genre, measure a paragraph against its own mean."""
    counts = _sentence_word_counts(paragraph)
    if len(counts) < MIN_ENDING_SENTENCES:
        return None
    average = fmean(counts)
    return counts[-1] / average if average else None


def _uniform_endings_rows(path: str, paragraphs: list[Paragraph]) -> list[dict]:
    found = [(paragraph, _ending_ratio(paragraph)) for paragraph in paragraphs]
    measured = [(paragraph, ratio) for paragraph, ratio in found if ratio is not None]
    if len(measured) < MIN_ENDING_PARAGRAPHS:
        return []
    punchy = [ratio <= PUNCHY_ENDING_RATIO for _paragraph, ratio in measured]
    if sum(punchy) / len(punchy) <= PUNCHY_SHARE_LIMIT:
        return []
    number, first_line = measured[0][0][0]
    return [spanning(finding_row(
        "english", "uniform_paragraph_endings", number,
        "Paragraphs all end on a short sentence in " + path,
        first_line, "Let some paragraphs end on their long sentence.",
    ), measured[-1][0][-1][0])]


def _three_item_finding(path: str, number: int, evidence: str) -> dict:
    return finding_row(
        "english", "three_item_list", number,
        "Passage uses a three-item list in " + path,
        evidence, "Use two items or vary the structure.",
    )


def _closes_a_longer_series(visible: str, start: int) -> bool:
    """Real four-item writing was reported as slop because a four-item list ends in a three-item tail."""
    return visible[:start].rstrip().endswith(",")


def _is_three_item_series(visible: str) -> bool:
    return any(
        not _closes_a_longer_series(visible, match.start())
        for match in THREE_ITEM_RE.finditer(visible)
    )


def _three_items_in_line(path: str, number: int, line: str) -> list[dict]:
    rows = []
    for _sentence_line, sentence in _sentences([(number, line)]):
        visible = _strip_inline_code(_strip_english_hidden(sentence))
        if _is_three_item_series(visible):
            rows.append(_three_item_finding(path, number, sentence))
    return rows


def _three_items_in_paragraph(path: str, paragraph: Paragraph) -> list[dict]:
    return [
        finding
        for number, line in paragraph
        for finding in _three_items_in_line(path, number, line)
    ]


def _three_item_rows(path: str, paragraphs: list[Paragraph]) -> list[dict]:
    rows = []
    for paragraph in paragraphs:
        rows.extend(_three_items_in_paragraph(path, paragraph))
    return rows


def _three_item_markdown_rows(path: str, lines: list[ProseLine]) -> list[dict]:
    rows = []
    run = ListRun()
    for number, line in [*lines, (0, "")]:
        if run.take(number, line, LIST_ITEM_RE.match(line) is not None):
            continue
        if forced_triad(run):
            rows.append(spanning(_three_item_finding(path, run.start, run.first), run.last))
        run = ListRun()
    return rows


def _paragraph_groups(path: str, lines: list[ProseLine]) -> list[Paragraph]:
    """Because rendered blocks can touch, give each markup paragraph its own block."""
    if PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS:
        return [[(number, line.strip())] for number, line in lines if line.strip()]
    return list(_paragraphs(lines))


def _rhythm_rows(path: str, lines: list[ProseLine]) -> list[dict]:
    paragraphs = _paragraph_groups(path, lines)
    rows = _low_variance_rows(path, paragraphs)
    rows.extend(_uniform_endings_rows(path, paragraphs))
    rows.extend(_three_item_rows(path, paragraphs))
    rows.extend(_three_item_markdown_rows(path, lines))
    return rows


def _is_list_continuation(line: str, count: int, item_indent: int) -> bool:
    if not count or not line.strip():
        return False
    return len(line) - len(line.lstrip()) > item_indent


def _oversized_list_rows(path: str, lines, cap: int) -> list[dict]:
    return [
        spanning(finding_row(
            "english", "oversized_list", span.start,
            "List exceeds the item cap in " + path,
            span.first_line, "Split the list into smaller ranked groups.",
        ), span.last)
        for span in _list_spans(lines)
        if span.count > cap
    ]


def _list_spans(lines: list[ProseLine]) -> Iterator[_ListSpan]:
    count = start = last = item_indent = 0
    first_line = ""
    for number, line in [*lines, (0, "")]:
        is_item = bool(LIST_ITEM_RE.match(line))
        if not is_item and _is_list_continuation(line, count, item_indent):
            last = number
            continue
        if is_item:
            item_indent = len(line) - len(line.lstrip())
            start, first_line = (number, line) if count == 0 else (start, first_line)
            count, last = count + 1, number
            continue
        if count:
            yield _ListSpan(start, first_line, last, count)
        count = 0


def scan_prose_structure(path: str, text: str, config: dict) -> list[dict]:
    lines = list(_markdown_prose_lines(text))
    list_cap = _int_setting(config, "list_item_cap", "ADW_LIST_ITEM_CAP", 8)
    findings = _oversized_list_rows(path, lines, list_cap)
    findings.extend(_rhythm_rows(path, lines))
    return findings
