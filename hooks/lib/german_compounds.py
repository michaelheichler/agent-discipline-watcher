"""Name a compound only when it splits into dictionary parts, because a syllable count flags loanwords and code."""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import NamedTuple

try:
    from .prose_language import INLINE_CODE_RE, PATH_RE, URL_RE
except ImportError:
    from prose_language import INLINE_CODE_RE, PATH_RE, URL_RE

LEXICON_PATH = Path(__file__).with_name("german_compound_lexicon.txt.gz")
SHORT_NOUNS_PATH = Path(__file__).with_name("german_short_nouns.json")
BLOCK_LETTERS = 25
# Hint from 14, because the lexicon split was measured from that length.
HINT_LETTERS = 14
MIN_PART = 3
SHORT_PART = 4
LINKING_ELEMENTS = ("", "s", "es", "n", "en", "er", "e", "ens")
HEAD_ENDINGS = ("", "n", "en", "e", "s", "er", "es", "em")
HEAD_STOPLIST = frozenset({
    "isch", "ische", "ischen", "ischer", "isches", "ischem",
    "lich", "liche", "lichen", "licher", "liches", "lichem",
    "ende", "enden", "ender", "endes", "endem",
    "heit", "keit", "schaft", "weise", "erweise", "ster", "teste",
    "elle", "ellen", "eller", "elles",
})
BOUND_PREFIXES = frozenset({
    "ent", "ver", "be", "er", "zer", "ge", "ur", "un", "miss", "inter", "anti", "para", "pseudo", "trans", "sub",
})
NISCHE_HEADS = frozenset({"nische", "nischen", "nischer", "nisches", "nischem"})
VOWELS = frozenset("aeiouäöüy")
UMLAUT_BASES = str.maketrans("äöü", "aou")
QUOTED_RE = re.compile(r"„[^“”\n]*[“”]|»[^«\n]*«|“[^”\n]*”|\"[^\"\n]*\"")
WORD_RE = re.compile(r"(?<!\w)[^\W\d_][a-zäöüß]*(?!\w)")
Span = tuple[int, int]
Splits = tuple[tuple[Span, ...], ...]


class Compound(NamedTuple):
    start: int
    word: str
    parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Lexicon:
    words: frozenset[str]
    short_nouns: frozenset[str]

    def allows(self, piece: str) -> bool:
        """Admit a three-letter part only from the curated list, because most three-letter entries are affixes."""
        return len(piece) >= SHORT_PART or piece in self.short_nouns

    def knows_head(self, piece: str) -> bool:
        if piece in HEAD_STOPLIST:
            return False
        return any(
            form in self.words and form not in HEAD_STOPLIST and self.allows(form) for form in _head_forms(piece)
        )

    def knows_part(self, piece: str) -> bool:
        if piece in BOUND_PREFIXES or not self.allows(piece):
            return False
        return piece in self.words or piece + "e" in self.words


def _head_forms(piece: str) -> list[str]:
    stems = [
        piece[:len(piece) - len(ending)] for ending in HEAD_ENDINGS
        if piece.endswith(ending) and len(piece) - len(ending) >= MIN_PART
    ]
    return stems + [stem.translate(UMLAUT_BASES) for stem in stems if stem.translate(UMLAUT_BASES) != stem]


def _link_ends(word: str, end: int) -> list[int]:
    return [
        end + len(link) for link in LINKING_ELEMENTS
        if word.startswith(link, end) and len(word) - end - len(link) >= MIN_PART
    ]


def _all_splits(word: str, lexicon: Lexicon) -> Splits:
    """Memoize by start offset, because every head choice reaches the same tails again."""
    @cache
    def tails(start: int) -> Splits:
        return tuple(parts for end in range(start + MIN_PART, len(word) + 1) for parts in pieces(start, end))

    def pieces(start: int, end: int) -> Splits:
        piece = word[start:end]
        if end == len(word):
            return (((start, end),),) if lexicon.knows_head(piece) else ()
        if not lexicon.knows_part(piece):
            return ()
        return tuple(((start, end), *rest) for next_start in _link_ends(word, end) for rest in tails(next_start))

    return tails(0)


def _nische_after_vowel(word: str, parts: tuple[Span, ...]) -> bool:
    """Reject Nische after a vowel, because -anisch adjectives split as a place name plus Nische and Marktnische does not."""
    (_start, before_end), (head_start, head_end) = parts[-2], parts[-1]
    return word[head_start:head_end] in NISCHE_HEADS and word[before_end - 1] in VOWELS


def _best_split(word: str, lexicon: Lexicon) -> tuple[Span, ...] | None:
    """Prefer the fewest parts, then the longest shortest part, because that ranking held in the frozen evaluation."""
    lowered = word.lower()
    splits = [
        parts for parts in _all_splits(lowered, lexicon)
        if len(parts) >= 2 and not _nische_after_vowel(lowered, parts)
    ]
    return min(splits, key=lambda parts: (len(parts), -min(end - start for start, end in parts)), default=None)


def _named_parts(word: str, split: tuple[Span, ...]) -> tuple[str, ...]:
    starts = [start for start, _end in split]
    pieces = (word[start:end] for start, end in zip(starts, [*starts[1:], len(word)], strict=True))
    return tuple(piece[:1].upper() + piece[1:] for piece in pieces)


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def _own_words(text: str) -> str:
    """Blank code, links, paths, and quotes at equal length, because they are not the writer's German and offsets must hold."""
    for pattern in (INLINE_CODE_RE, URL_RE, PATH_RE, QUOTED_RE):
        text = pattern.sub(_blank, text)
    return text


@cache
def _lexicon() -> Lexicon:
    with gzip.open(LEXICON_PATH, "rt", encoding="utf-8") as handle:
        words = frozenset(handle.read().split())
    return Lexicon(words, frozenset(json.loads(SHORT_NOUNS_PATH.read_text(encoding="utf-8"))))


def compounds(text: str) -> list[Compound]:
    """Read the lexicon only for a long candidate, because most German paragraphs hold none and the load costs time."""
    candidates = [found for found in WORD_RE.finditer(_own_words(text)) if len(found.group(0)) >= HINT_LETTERS]
    if not candidates:
        return []
    lexicon = _lexicon()
    found = ((candidate.start(), candidate.group(0)) for candidate in candidates)
    splits = ((start, word, _best_split(word, lexicon)) for start, word in found)
    return [Compound(start, word, _named_parts(word, split)) for start, word, split in splits if split]
