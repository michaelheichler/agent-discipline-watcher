"""Share sentence and line arithmetic, because every German rule module reports the same hit shape."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

try:
    from . import Hit
    from ..german_readability import SENTENCE_BREAK_RE
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit
    from german_readability import SENTENCE_BREAK_RE
    from prose_language import ParagraphLanguage

QUOTED_RE = re.compile(r"„[^“”\n]*[“”]|»[^«\n]*«")
DELIMITER_CELL = r"\s*:?-+:?\s*"
DELIMITER_ROW_RE = re.compile(r"\s*\|?" + DELIMITER_CELL + r"(?:\|" + DELIMITER_CELL + r")*\|?\s*")
CELL_PIPE_RE = re.compile(r"\s*(?<!\\)\|\s*")
CODE_SPAN_RE = re.compile(r"(?<![`\\])(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
SentenceFinder = Callable[[str], "re.Match[str] | None"]
Span = tuple[int, int]


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def visible(text: str) -> str:
    """Blank quoted speech at equal length, because a cited phrase is not the writer's own style and offsets must hold."""
    return QUOTED_RE.sub(_blank, text)


def _pieces(text: str, cuts: Iterable[Span]) -> list[tuple[int, str]]:
    pieces, start = [], 0
    for low, high in sorted(cuts):
        pieces.append((start, text[start:low]))
        start = high
    pieces.append((start, text[start:]))
    return [(offset, piece) for offset, piece in pieces if piece.strip()]


def sentence_spans(text: str) -> list[tuple[int, str]]:
    """Keep each start offset, because a hit reports the line its sentence sits on."""
    return _pieces(text, (found.span() for found in SENTENCE_BREAK_RE.finditer(text)))


def _is_delimiter_row(text: str, start: int, end: int) -> bool:
    return "|" in text[start:end] and DELIMITER_ROW_RE.fullmatch(text, start, end) is not None


def _table_lines(paragraph: ParagraphLanguage) -> list[Span]:
    """Start at the header above the delimiter row, because a GFM table runs to the end of its paragraph."""
    lines = paragraph.line_spans()
    rows = (index for index, (start, end) in enumerate(lines) if index and _is_delimiter_row(paragraph.text, start, end))
    delimiter = next(rows, None)
    return [] if delimiter is None else lines[delimiter - 1:]


def _row_cuts(text: str, start: int, end: int) -> list[Span]:
    """Cut at the line break too, because a row without outer pipes would run into the line above."""
    return [(max(start - 1, 0), start), *(found.span() for found in CELL_PIPE_RE.finditer(text, start, end))]


def _cell_cuts(paragraph: ParagraphLanguage) -> list[Span]:
    return [cut for start, end in _table_lines(paragraph) for cut in _row_cuts(paragraph.text, start, end)]


def text_units(paragraph: ParagraphLanguage) -> list[tuple[int, str]]:
    """Split a table into cells before blanking code, because a raw pipe ends a cell even inside backticks."""
    units = ((offset, CODE_SPAN_RE.sub(_blank, piece)) for offset, piece in _pieces(visible(paragraph.text), _cell_cuts(paragraph)))
    return [(offset, unit) for offset, unit in units if unit.strip()]


def _paragraph_spans(paragraph: ParagraphLanguage) -> list[tuple[int, str]]:
    return [(offset + inner, sentence) for offset, unit in text_units(paragraph) for inner, sentence in sentence_spans(unit)]


def closing_sentences(paragraph: ParagraphLanguage) -> list[tuple[int, str]]:
    closings = ((offset, sentence_spans(unit)[-1]) for offset, unit in text_units(paragraph))
    return [(offset + inner, sentence) for offset, (inner, sentence) in closings]


def placed(paragraph: ParagraphLanguage, span: Span, hit: Hit) -> Hit:
    """Place the hit on its own lines, because a paragraph span blocks provenance narrowing."""
    line, end_line = paragraph.lines_of(*span)
    return hit._replace(line=line, end_line=end_line)


def _containing(spans: list[tuple[int, str]], index: int) -> str:
    chosen = spans[0][1] if spans else ""
    for offset, sentence in spans:
        if offset <= index:
            chosen = sentence
    return chosen


def _unit_phrase_hits(rule: str, paragraph: ParagraphLanguage, unit: tuple[int, str], pattern: re.Pattern[str]) -> list[Hit]:
    offset, text = unit
    spans = sentence_spans(text)
    return [
        placed(paragraph, (offset + found.start(), offset + found.end()), Hit(rule, paragraph.line, _containing(spans, found.start()), found.group(0)))
        for found in pattern.finditer(text)
    ]


def phrase_hits(rule: str, paragraphs: list[ParagraphLanguage], pattern: re.Pattern[str]) -> list[Hit]:
    """Report each match with its sentence, because the reader rewrites the sentence, not the word."""
    return [
        hit for paragraph in paragraphs for unit in text_units(paragraph)
        for hit in _unit_phrase_hits(rule, paragraph, unit, pattern)
    ]


def _paragraph_sentence_hits(rule: str, paragraph: ParagraphLanguage, finder: SentenceFinder) -> list[Hit]:
    found = [(offset, sentence, finder(sentence)) for offset, sentence in _paragraph_spans(paragraph)]
    return [
        placed(paragraph, (offset + match.start(), offset + match.end()), Hit(rule, paragraph.line, sentence, match.group(0)))
        for offset, sentence, match in found if match is not None
    ]


def sentence_hits(rule: str, paragraphs: list[ParagraphLanguage], finder: SentenceFinder) -> list[Hit]:
    """Report one hit per sentence, because these rules judge the sentence as a whole."""
    return [hit for paragraph in paragraphs for hit in _paragraph_sentence_hits(rule, paragraph, finder)]
