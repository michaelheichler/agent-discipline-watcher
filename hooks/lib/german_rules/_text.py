"""Share sentence and line arithmetic, because every German rule module reports the same hit shape."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

try:
    from . import Hit
    from ..german_readability import sentence_spans as _readability_spans, words
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit
    from german_readability import sentence_spans as _readability_spans, words
    from prose_language import ParagraphLanguage

QUOTED_RE = re.compile(r"„[^“”\n]*[“”]|»[^«\n]*«")
DELIMITER_CELL = r"\s*:?-+:?\s*"
DELIMITER_ROW_RE = re.compile(r"\s*\|?" + DELIMITER_CELL + r"(?:\|" + DELIMITER_CELL + r")*\|?\s*")
CELL_PIPE_RE = re.compile(r"\s*(?<!\\)\|\s*")
CODE_SPAN_RE = re.compile(r"(?<![`\\])(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
SentenceFinder = Callable[[str], "re.Match[str] | Iterable[re.Match[str]] | None"]
Span = tuple[int, int]
SentenceUnless = Callable[[str, re.Match[str]], bool]


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
    return _readability_spans(text)


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


def line_units(paragraph: ParagraphLanguage) -> list[tuple[int, str]]:
    """Retain physical lines, because scanner paragraphs flatten Markdown block boundaries."""
    text = CODE_SPAN_RE.sub(_blank, visible(paragraph.text))
    return [(start, text[start:end]) for start, end in paragraph.line_spans()]


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


def _paragraph_sentence_hits(
    rule: str, paragraph: ParagraphLanguage, finder: SentenceFinder | re.Pattern[str],
    unless: SentenceUnless | None,
) -> list[Hit]:
    found = []
    for offset, sentence in _paragraph_spans(paragraph):
        result = finder.finditer(sentence) if isinstance(finder, re.Pattern) else finder(sentence)
        if result is None:
            continue
        matches = (result,) if isinstance(result, re.Match) else result
        found.extend((offset, sentence, match) for match in matches
                     if unless is None or not unless(sentence, match))
    return [
        placed(paragraph, (offset + match.start(), offset + match.end()), Hit(rule, paragraph.line, sentence, match.group(0)))
        for offset, sentence, match in found
    ]


def sentence_hits(
    rule: str, paragraphs: list[ParagraphLanguage], finder: SentenceFinder | re.Pattern[str],
    *, unless: SentenceUnless | None = None,
) -> list[Hit]:
    """Because sentence filters retain their own matches, preserve every retained match and its placement."""
    return [hit for paragraph in paragraphs for hit in _paragraph_sentence_hits(rule, paragraph, finder, unless)]


FAMILY_ENDINGS = r"(?:e|en|er|es|em|s|n|t|st|et|est|te|ten|test|tet|ete|eten)?"
FAMILY_GAP = r"(?:\s+[\wÄÖÜäöüß-]+){0,6}"


def phrase_families(*families: str) -> str:
    """Bound inflections and gaps, because phrase variants must not match arbitrary word tails."""
    alternatives = []
    for family in families:
        tokens = []
        for token in family.split():
            if token == "...":
                tokens.append(FAMILY_GAP)
            else:
                forms = (re.escape(part.removesuffix("~")) + (FAMILY_ENDINGS if part.endswith("~") else "")
                         for part in token.split("/"))
                tokens.append(r"\s+(?:" + "|".join(forms) + r")\b")
        alternatives.append(r"\b" + "".join(tokens).removeprefix(r"\s+"))
    return "(?i:" + "|".join(alternatives) + ")"


EVIDENCE_RE = re.compile(
    r"\b(?:\d+(?:[.,]\d+)?|null|ein[ensmr]?|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s+"
    r"(?:ms|s|Sekunden?|Minuten?|Stunden?|Tage[n]?|Schritte[n]?|Abschnitte[n]?|Prozent|Millisekunden?)\b"
    r"|[;:]\s*[^.!?;:]{0,90}\b(?:zeigt|liefert|ergibt|gibt|bestätigt)\b[^.!?;:]{0,30}\b\d+\b"
    r"|\b(?:Messung|Benchmark|Prüfbericht)\b[^.!?;:]{0,60}\b\d+\b", re.IGNORECASE,
)
CLAIM_BOUNDARY_RE = re.compile(r"[;:]|,\s+(?:aber|doch|sondern)\b|\bund\s+(?=(?:der|die|das)\b)")
OBSERVABLE_STATE = r"(?:erreichbar|verfügbar|aktiv|inaktiv|vorhanden|abgelaufen|leer|beendet|gestartet|gestoppt)"
STATE_COPULA = r"(?:ist|sind|war|waren|bleibt|bleiben)"
OBSERVABLE_STATE_RE = re.compile(
    r"\b(?:" + STATE_COPULA + r"\s+" + OBSERVABLE_STATE + "|"
    + OBSERVABLE_STATE + r"\s+" + STATE_COPULA + r")\b", re.IGNORECASE,
)
CLAIM_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
CONTRAST_RE = re.compile(
    r"\b(?:alte[nmrs]?|bisherige[nmrs]?|weiterhin|stattdessen|dagegen|anders\s+als|im\s+Gegensatz)\b",
    re.IGNORECASE,
)


def has_evidence(sentence: str) -> bool:
    """Keep measurable support, because a supported claim is not empty emphasis."""
    return EVIDENCE_RE.search(sentence) is not None


def evidence_context(sentence: str, index: int) -> str:
    """Because evidence supports a nearby claim, stop at the next independent assertion."""
    boundaries = list(CLAIM_BOUNDARY_RE.finditer(sentence))
    start = max((found.end() for found in boundaries if found.end() <= index), default=0)
    following = [found for found in boundaries if found.start() > index]
    if not following:
        return sentence[start:]
    boundary = following[0]
    end = following[1].start() if len(following) > 1 else len(sentence)
    if boundary.group() in {";", ":"} and has_evidence(sentence[boundary.start():end]):
        return sentence[start:end]
    return sentence[start:boundary.start()]


def has_observable_state(sentence: str) -> bool:
    """Because operational states can be checked, distinguish them from evaluative summary claims."""
    return OBSERVABLE_STATE_RE.search(sentence) is not None


def sentence_contexts(paragraphs: list[ParagraphLanguage]) -> list[tuple[ParagraphLanguage, int, str, str]]:
    """Carry the preceding sentence, because summary and contrast depend on adjacent claims."""
    contexts, previous = [], ""
    for paragraph in paragraphs:
        for offset, sentence in sentence_spans(paragraph.text):
            contexts.append((paragraph, offset, sentence, previous))
            previous = sentence
    return contexts


def repeats_claim(sentence: str, previous: str) -> bool:
    """Compare content words, because a summary needs a prior claim to repeat."""
    current_numbers = set(CLAIM_NUMBER_RE.findall(sentence))
    previous_numbers = set(CLAIM_NUMBER_RE.findall(previous))
    if current_numbers - previous_numbers:
        return False
    current_words = {word.casefold() for word in words(sentence) if len(word) > 4}
    previous_words = {word.casefold() for word in words(previous) if len(word) > 4}
    return len(current_words & previous_words) >= 2


def has_contrast(sentence: str) -> bool:
    """Keep explicit alternatives, because contrast particles connect distinct claims."""
    return CONTRAST_RE.search(sentence) is not None
