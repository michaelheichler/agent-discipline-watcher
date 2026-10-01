"""German Wikipedia names both formulas in N-003, because that keeps each weight checkable against the cited source."""
from __future__ import annotations

import re

try:
    from .german_syllables import count_syllables
except ImportError:
    from german_syllables import count_syllables

WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])")
LONG_WORD_LETTERS = 6
LONG_SYLLABLE_COUNT = 3


def sentences(text: str) -> list[str]:
    """A bare split on whitespace would also cut a mid-sentence abbreviation, because only a capital after the mark reads as a real boundary."""
    return [part for part in SENTENCE_BREAK_RE.split(text.strip()) if part.strip()]


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def lix(text: str) -> float:
    """Björnsson's own weights stay exact here, because N-003 cites the source and a changed constant would drift from it unseen."""
    sentence_list = sentences(text) or [text]
    word_list = words(text)
    if not word_list:
        return 0.0
    long_words = sum(1 for word in word_list if len(word) > LONG_WORD_LETTERS)
    return len(word_list) / len(sentence_list) + 100 * long_words / len(word_list)


def wiener_sachtextformel_1(text: str) -> float:
    """Bamberger and Vanecek's first form keeps its exact weights, because N-003 cites the source formula for this to match."""
    sentence_list = sentences(text) or [text]
    word_list = words(text)
    if not word_list:
        return 0.0
    syllable_counts = [count_syllables(word) for word in word_list]
    long_syllable_share = 100 * sum(1 for count in syllable_counts if count >= LONG_SYLLABLE_COUNT) / len(word_list)
    sentence_length = len(word_list) / len(sentence_list)
    long_letter_share = 100 * sum(1 for word in word_list if len(word) > LONG_WORD_LETTERS) / len(word_list)
    one_syllable_share = 100 * sum(1 for count in syllable_counts if count == 1) / len(word_list)
    return (
        0.1935 * long_syllable_share
        + 0.1672 * sentence_length
        + 0.1297 * long_letter_share
        - 0.0327 * one_syllable_share
        - 0.875
    )
