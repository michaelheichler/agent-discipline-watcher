"""Share sentence and line arithmetic, because every German rule module reports the same hit shape."""
from __future__ import annotations

import re
from collections.abc import Callable

try:
    from . import Hit
    from ..german_readability import SENTENCE_BREAK_RE
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit
    from german_readability import SENTENCE_BREAK_RE
    from prose_language import ParagraphLanguage

QUOTED_RE = re.compile(r"„[^“”\n]*[“”]|»[^«\n]*«")
SentenceFinder = Callable[[str], "re.Match[str] | None"]


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def visible(text: str) -> str:
    """Blank quoted speech at equal length, because a cited phrase is not the writer's own style and offsets must hold."""
    return QUOTED_RE.sub(_blank, text)


def sentence_spans(text: str) -> list[tuple[int, str]]:
    """Keep each start offset, because a hit reports the line its sentence sits on."""
    spans, start = [], 0
    for boundary in SENTENCE_BREAK_RE.finditer(text):
        spans.append((start, text[start:boundary.start()]))
        start = boundary.end()
    spans.append((start, text[start:]))
    return [(offset, sentence) for offset, sentence in spans if sentence.strip()]


def line_at(paragraph: ParagraphLanguage, index: int) -> int:
    return paragraph.line + paragraph.text.count("\n", 0, index)


def _containing(spans: list[tuple[int, str]], index: int) -> str:
    chosen = spans[0][1] if spans else ""
    for offset, sentence in spans:
        if offset <= index:
            chosen = sentence
    return chosen


def phrase_hits(rule: str, paragraphs: list[ParagraphLanguage], pattern: re.Pattern[str]) -> list[Hit]:
    """Report each match with its sentence, because the reader rewrites the sentence, not the word."""
    hits = []
    for paragraph in paragraphs:
        text = visible(paragraph.text)
        spans = sentence_spans(text)
        hits.extend(
            Hit(rule, line_at(paragraph, found.start()), _containing(spans, found.start()), found.group(0))
            for found in pattern.finditer(text)
        )
    return hits


def _paragraph_sentence_hits(rule: str, paragraph: ParagraphLanguage, finder: SentenceFinder) -> list[Hit]:
    found = [(offset, sentence, finder(sentence)) for offset, sentence in sentence_spans(visible(paragraph.text))]
    return [
        Hit(rule, line_at(paragraph, offset + match.start()), sentence, match.group(0))
        for offset, sentence, match in found if match is not None
    ]


def sentence_hits(rule: str, paragraphs: list[ParagraphLanguage], finder: SentenceFinder) -> list[Hit]:
    """Report one hit per sentence, because these rules judge the sentence as a whole."""
    return [hit for paragraph in paragraphs for hit in _paragraph_sentence_hits(rule, paragraph, finder)]
