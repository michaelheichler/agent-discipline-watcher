"""T-004 owns scanner.py, because only that ticket may edit it without the two changes colliding."""
from __future__ import annotations

from statistics import fmean, pstdev

try:
    from .comment_rules import _finding
    from .german_readability import sentences, words
    from .german_syllables import count_syllables
    from .prose_language import ParagraphLanguage
except ImportError:
    from comment_rules import _finding
    from german_readability import sentences, words
    from german_syllables import count_syllables
    from prose_language import ParagraphLanguage

FAMILY = "english"
SENTENCE_LENGTH_CAP = 20
RHYTHM_MIN_SENTENCES = 8
RHYTHM_VARIATION_LIMIT = 0.4
UNIFORM_PARAGRAPH_MIN_COUNT = 4
UNIFORM_PARAGRAPH_SPREAD = 2
CONNECTOR_OPENERS = ("darüber hinaus", "außerdem", "ferner", "ebenfalls")
CONNECTOR_DENSITY_CAP = 1
LONG_COMPOUND_SYLLABLES = 6


def _sentence_word_counts(paragraph: ParagraphLanguage) -> list[int]:
    return [len(words(sentence)) for sentence in sentences(paragraph.text)]


def _satzlaenge_rows(path: str, paragraph: ParagraphLanguage) -> list[dict]:
    """BAköV and Gottschling set this cap from a reader's working memory, because that limit is measured, not a style choice."""
    rows = []
    for sentence in sentences(paragraph.text):
        count = len(words(sentence))
        if count > SENTENCE_LENGTH_CAP:
            rows.append(_finding(
                FAMILY, "de_sentence_length", paragraph.line,
                "Sentence runs past " + str(SENTENCE_LENGTH_CAP) + " words in " + path,
                sentence, "Split the sentence at one clause boundary.",
            ))
    return rows


def _gleichfoermiger_rhythmus_rows(path: str, paragraphs: list[ParagraphLanguage]) -> list[dict]:
    """`rhythm_lint.py` names 0.4 as the cutoff, because that threshold held after a 2026-07 revalidation."""
    counts = [count for paragraph in paragraphs for count in _sentence_word_counts(paragraph)]
    if len(counts) < RHYTHM_MIN_SENTENCES:
        return []
    variation = pstdev(counts) / fmean(counts)
    if variation >= RHYTHM_VARIATION_LIMIT:
        return []
    return [_finding(
        FAMILY, "de_uniform_rhythm", paragraphs[0].line,
        "Sentence lengths stay uniform across the German text in " + path,
        paragraphs[0].text, "Vary the sentence lengths across the document.",
    )]


def _isometrisches_dokument_rows(path: str, paragraphs: list[ParagraphLanguage]) -> list[dict]:
    """`rhythm_lint.py` names this spread as uniform, because the repeat is frequent enough to call the whole document even."""
    if len(paragraphs) < UNIFORM_PARAGRAPH_MIN_COUNT:
        return []
    sentence_counts = [len(sentences(paragraph.text)) for paragraph in paragraphs]
    if max(sentence_counts) - min(sentence_counts) > UNIFORM_PARAGRAPH_SPREAD:
        return []
    return [_finding(
        FAMILY, "de_uniform_paragraphs", paragraphs[0].line,
        "Every German paragraph holds close to the same length in " + path,
        paragraphs[0].text, "Let some paragraphs run shorter or longer than the rest.",
    )]


def _opens_with_connector(sentence: str) -> bool:
    stripped = sentence.strip().lower()
    return stripped.startswith(CONNECTOR_OPENERS)


def _mechanische_konjunktionen_rows(path: str, paragraph: ParagraphLanguage) -> list[dict]:
    """`rhythm_lint.py` flags this paragraph shape, because a second sentence on the same connector reads as a filler tic."""
    opener_count = sum(1 for sentence in sentences(paragraph.text) if _opens_with_connector(sentence))
    if opener_count <= CONNECTOR_DENSITY_CAP:
        return []
    return [_finding(
        FAMILY, "de_repeated_connector", paragraph.line,
        "Paragraph opens more than one sentence on a stock connector in " + path,
        paragraph.text, "Open at most one sentence in the paragraph with a connector like außerdem.",
    )]


def _long_compound_rows(path: str, paragraph: ParagraphLanguage) -> list[dict]:
    """Gottschling ties six syllables to one eye fixation, because past that point a compound stops reading as one word."""
    rows = []
    for word in words(paragraph.text):
        if count_syllables(word) >= LONG_COMPOUND_SYLLABLES:
            rows.append(_finding(
                FAMILY, "de_long_compound", paragraph.line,
                "Compound runs past " + str(LONG_COMPOUND_SYLLABLES) + " syllables with no hyphen in " + path,
                word, "Add a hyphen split or rewrite the compound as a genitive phrase.",
            ))
    return rows


def scan_german_document(path: str, paragraphs: list[ParagraphLanguage], config: dict) -> list[dict]:
    """Only the German rows reach this function, because a caller already split the paragraphs by language."""
    del config
    rows = []
    for paragraph in paragraphs:
        rows.extend(_satzlaenge_rows(path, paragraph))
        rows.extend(_mechanische_konjunktionen_rows(path, paragraph))
        rows.extend(_long_compound_rows(path, paragraph))
    rows.extend(_gleichfoermiger_rhythmus_rows(path, paragraphs))
    rows.extend(_isometrisches_dokument_rows(path, paragraphs))
    return rows
