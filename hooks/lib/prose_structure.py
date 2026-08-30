"""Split from scanner.py because sentence and list checks do not depend on comment or docstring rules."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePath
from statistics import fmean, pstdev

try:
    from .comment_rules import _finding
    from .markup import MIXED_LANGUAGE_EXTS, _strip_english_hidden, _strip_inline_code
    from .scan_input import int_setting as _int_setting
except ImportError:
    from comment_rules import _finding
    from markup import MIXED_LANGUAGE_EXTS, _strip_english_hidden, _strip_inline_code
    from scan_input import int_setting as _int_setting

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_REFERENCE_RE = re.compile(r"^\s*\[[^]]+\]:\s+\S")
TABLE_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
# Masked because a heading is a title, and scanning it reported phrase findings against labels like COMPREHENSIVE TECHNICAL STANDARDS.
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
SETEXT_RE = re.compile(r"^\s{0,3}(?:={2,}|-{2,})\s*$")
# Masked only under a list marker, because a prose sentence may also carry a colon and must still be scanned.
LABEL_LINE_RE = re.compile(r"^\s*[-+*]\s+(?:\[[ xX]\]\s*)?(?:\*{2}[^*]{1,40}\*{2}|`[^`]{1,40}`)\s*:")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
WORD_RE = re.compile(r"\b\w+(?:[-']\w+)*\b")
THREE_ITEM_RE = re.compile(
    r"\b(?:[a-z]+\s+){0,2}[a-z]+,\s+(?!(?:which|we|i|it|they|he|she|because)\b)"
    r"(?:[a-z]+\s+){0,2}[a-z]+,\s+(?:and|or)\s+"
    r"(?!(?:which|we|i|it|they|he|she|because)\b)(?:[a-z]+\s+){0,2}[a-z]+(?=[.!?)]|$)",
    re.IGNORECASE,
)
MIN_VARIANCE_SENTENCES = 4
MIN_MEASURED_WORDS = 5
# Set to 1.5 because Tukey's fence lands at 36.5 words on 5000 tracked sentences and flags 3.46 percent of them.
TUKEY_MULTIPLIER = 1.5
MIN_TUKEY_SENTENCES = 8
# Floored at 28 because that is the measured p90, so a file of short sentences cannot drag the cap into normal prose.
MIN_DYNAMIC_CAP = 28
# Set to the measured p05 of 709 real paragraphs, because the previous 0.32 sat near the median and flagged 33.85 percent of ordinary writing.
SENTENCE_VARIATION_LIMIT = 0.16
RHYTHM_LIMITATIONS = {
    "low_sentence_variance": (
        "The threshold is the p05 of 709 real paragraphs, and the essay corpus holds one "
        "truncated paragraph per row, so it yields no true positive to measure against."
    ),
}
MIN_ENDING_SENTENCES = 2
MIN_ENDING_PARAGRAPHS = 3
# WHY: The p25 of 30700 human paragraph endings in corpus_paragraphs.jsonl, recorded in evals/paragraph_endings.json.
PUNCHY_ENDING_RATIO = 0.7018
# WHY: The p95 of the same corpus's 4570 human documents, which fires on 3.15 percent of them.
PUNCHY_SHARE_LIMIT = 0.6667
ProseLine = tuple[int, str]
Paragraph = list[ProseLine]


def _next_fence(line: str, fence: str | None) -> tuple[str | None, bool]:
    marker = FENCE_RE.match(line)
    if not marker:
        return fence, False
    marker_kind = marker.group(1)[0]
    if fence is None:
        return marker_kind, True
    return (None if marker_kind == fence else fence), True


def _next_frontmatter(line: str, number: int, active: bool) -> bool:
    if not active:
        return False
    return number == 1 or line.strip() not in ("---", "...")


def _is_nonprose_line(line: str) -> bool:
    """Grouped so the caller stays readable, because these are one question asked seven ways."""
    if line.lstrip().startswith((">", "|")):
        return True
    return any(
        pattern.match(line)
        for pattern in (TABLE_DELIMITER_RE, LINK_REFERENCE_RE, HEADING_RE, SETEXT_RE, LABEL_LINE_RE)
    )


def _markdown_prose_lines(text: str) -> Iterator[tuple[int, str]]:
    fence = None
    frontmatter = text.startswith("---\n")
    for number, line in enumerate(text.splitlines(), 1):
        in_frontmatter = frontmatter
        frontmatter = _next_frontmatter(line, number, frontmatter)
        if in_frontmatter:
            yield number, ""
            continue
        fence, is_marker = _next_fence(line, fence)
        if is_marker or fence or _is_nonprose_line(line):
            yield number, ""
            continue
        yield number, line


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


def _sentence_lengths(lines) -> list[int]:
    return [
        len(WORD_RE.findall(_strip_inline_code(_strip_english_hidden(sentence))))
        for paragraph in _paragraphs(lines)
        for _number, sentence in _sentences(paragraph)
    ]


def _quartile(ordered: list[int], fraction: float) -> float:
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _dynamic_cap(lengths: list[int], cap: int) -> int:
    """Tukey upper fence, because a fixed cap flags dense prose constantly and terse prose never."""
    usable = sorted(value for value in lengths if value >= MIN_MEASURED_WORDS)
    if len(usable) < MIN_TUKEY_SENTENCES:
        return cap
    first, third = _quartile(usable, 0.25), _quartile(usable, 0.75)
    return max(MIN_DYNAMIC_CAP, int(third + TUKEY_MULTIPLIER * (third - first)))


def _long_sentences_in_paragraph(path: str, paragraph, cap: int) -> list[dict]:
    rows = []
    for number, sentence in _sentences(paragraph):
        visible = _strip_inline_code(_strip_english_hidden(sentence))
        if len(WORD_RE.findall(visible)) > cap:
            rows.append(_finding(
                "english", "long_sentence", number,
                "Sentence runs past " + str(cap) + " words, the length this document sustains, in " + path,
                sentence, "Cut a clause or break at one clause boundary. Do not chop it into fragments.",
            ))
    return rows


def _long_sentence_rows(path: str, lines, cap: int) -> list[dict]:
    rows = []
    for paragraph in _paragraphs(lines):
        rows.extend(_long_sentences_in_paragraph(path, paragraph, cap))
    return rows


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
        rows.append(_finding(
            "english", "low_sentence_variance", number,
            "Paragraph has uniform sentence lengths in " + path,
            first_line, "Vary the sentence lengths in this paragraph.",
        ))
    return rows


def _ending_ratio(paragraph: Paragraph) -> float | None:
    """A paragraph is measured against its own mean because absolute sentence length differs by genre."""
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
    return [_finding(
        "english", "uniform_paragraph_endings", number,
        "Paragraphs all end on a short sentence in " + path,
        first_line, "Let some paragraphs end on their long sentence.",
    )]


def _three_item_finding(path: str, number: int, evidence: str) -> dict:
    return _finding(
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
    count = 0
    start = 0
    first_line = ""
    item_indent = 0
    for number, line in [*lines, (0, "")]:
        marker = LIST_ITEM_RE.match(line)
        indent = len(line) - len(line.lstrip())
        if marker and (count == 0 or indent == item_indent):
            start, first_line = (number, line) if count == 0 else (start, first_line)
            item_indent = indent
            count += 1
            continue
        if marker and indent > item_indent:
            continue
        if not line.strip() and count and number:
            continue
        if _is_list_continuation(line, count, item_indent):
            continue
        if count == 3:
            rows.append(_three_item_finding(path, start, first_line))
        count = 0
    return rows


def _paragraph_groups(path: str, lines: list[ProseLine]) -> list[Paragraph]:
    """Markup gets one block per paragraph, because a rendered document leaves no blank line between two adjacent blocks."""
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
    rows = []
    count = 0
    start = 0
    first_line = ""
    item_indent = 0
    for number, line in lines:
        is_item = bool(LIST_ITEM_RE.match(line))
        continues_list = not is_item and _is_list_continuation(line, count, item_indent)
        if continues_list:
            continue
        if not is_item:
            count = 0
            continue
        item_indent = len(line) - len(line.lstrip())
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
    findings = _long_sentence_rows(path, lines, _dynamic_cap(_sentence_lengths(lines), sentence_cap))
    findings.extend(_oversized_list_rows(path, lines, list_cap))
    findings.extend(_rhythm_rows(path, lines))
    return findings
