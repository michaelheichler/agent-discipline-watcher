"""Flag a run of bare main clauses split apart, because humanizer pattern 51 names it and the old length caps pushed agents into it."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePath
from typing import NamedTuple

try:
    from .comment_rules import _finding
    from .markup import INLINE_CODE_RE, MIXED_LANGUAGE_EXTS
    from .parataxis_lexicon import ABBREVIATIONS, ENGLISH, GERMAN as GERMAN_LEXICON, Lexicon
    from .prose_language import GERMAN
    from .prose_structure import LIST_ITEM_RE, Paragraph, ProseLine, _markdown_prose_lines, _source_line
except ImportError:
    from comment_rules import _finding
    from markup import INLINE_CODE_RE, MIXED_LANGUAGE_EXTS
    from parataxis_lexicon import ABBREVIATIONS, ENGLISH, GERMAN as GERMAN_LEXICON, Lexicon
    from prose_language import GERMAN
    from prose_structure import LIST_ITEM_RE, Paragraph, ProseLine, _markdown_prose_lines, _source_line

FAMILY = "english"
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])")
WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
OPENING_MARKS = "([{\"'" + chr(0x201E) + chr(0x201C) + chr(0xBB)
MAX_INITIAL_LETTERS = 2
# Because das alte System opens on an article, while das misst opens on a pronoun.
ADJECTIVE_ENDINGS = ("e", "en", "em", "er", "es")
# Code points, because the source may not hold these dashes and quotes.
QUOTE_AND_DASH = "".join(chr(code) for code in (0x201E, 0x201C, 0x201D, 0x201A, 0xAB, 0xBB, 0x2013, 0x2014, 0x2026))
# Because these marks join clauses, while 2.4 or 14:30 joins nothing.
JOINING_MARK_RE = re.compile(r"[,;()\[\]\"/" + QUOTE_AND_DASH + r"]|\.\.|\.(?!\d)\w|(?<!\d):|:(?!\d)")
# Because a dot inside inline code would split one sentence into two.
CODE_LETTER = "c"
INDENTED_BLOCK = 2
MIN_LOWERCASE_WORDS = 2
ACTION = (
    "Join the sentences that belong together. Use a subordinate clause (because, when, so that, after), "
    "a relative clause (which, who), an apposition, a participle phrase, or and or but. "
    "Em dashes, en dashes, and semicolons stay banned, so a comma or a conjunction does the joining. "
    "Example: 'The hook reads the file. It checks every rule.' becomes "
    "'The hook reads the file and checks every rule.'"
)


class Thresholds(NamedTuple):
    """Three in any run, because the reviewer now decides and pattern 51 runs of four missed half the chops."""

    min_run: int = 3
    linked_min_run: int = 3
    min_words: int = 3
    max_words: int = 12
    max_fronted: int = 2


class Sentence(NamedTuple):
    line: int
    text: str
    shown: str = ""


def _words_of(sentence: str) -> list[str]:
    return WORD_RE.findall(sentence)


def _pronoun_after_article(rest: list[str]) -> bool:
    """Skip inflected adjectives, because a capital after them marks a noun and so an article."""
    if not rest or rest[0][:1].isupper():
        return False
    adjectives = 0
    while adjectives < len(rest) and rest[adjectives][:1].islower() and rest[adjectives].endswith(ADJECTIVE_ENDINGS):
        adjectives += 1
    return not (adjectives and adjectives < len(rest) and rest[adjectives][:1].isupper())


def opens_with_back_reference(sentence: str, lexicon: Lexicon) -> bool:
    words = _words_of(sentence)
    if not words or words[0].lower() not in lexicon.back_references:
        return False
    if words[0].lower() in lexicon.articles:
        return _pronoun_after_article(words[1:])
    return True


def _opens_fronted(sentence: str, lexicon: Lexicon) -> bool:
    words = _words_of(sentence)
    return bool(words) and (words[0].lower() in lexicon.fronted or words[0][0].isdigit())


def reads_as_prose(words: list[str], lexicon: Lexicon) -> bool:
    """Demand lowercase words, because titles and captions have few, while a closing 14:30 is ordinary prose."""
    rest = words[1:]
    lowercase = sum(word[0].islower() for word in rest)
    if lowercase < MIN_LOWERCASE_WORDS:
        return False
    return lowercase / len(rest) >= lexicon.min_lowercase_share


def bare_main_clause(sentence: str, lexicon: Lexicon, limits: Thresholds) -> bool:
    """Reject any joining mark or word, because a writer who joined a clause did not split it."""
    text = sentence.strip()
    if not text.endswith(".") or JOINING_MARK_RE.search(text):
        return False
    words = _words_of(text)
    if not limits.min_words <= len(words) <= limits.max_words or not reads_as_prose(words, lexicon):
        return False
    if lexicon.joining_re is not None and lexicon.joining_re.search(text):
        return False
    checked = words[1:] if opens_with_back_reference(text, lexicon) else words
    return not any(word.lower() in lexicon.joiners for word in checked)


def _qualifies(run: list[Sentence], lexicon: Lexicon, limits: Thresholds) -> bool:
    """Let a pronoun chain shorten the run, because a sentence opening on It or Sie was cut from the one before."""
    if sum(_opens_fronted(sentence.text, lexicon) for sentence in run) > limits.max_fronted:
        return False
    if len(run) >= limits.min_run:
        return True
    linked = any(opens_with_back_reference(sentence.text, lexicon) for sentence in run[1:])
    return linked and len(run) >= limits.linked_min_run


def bare_runs(sentences: list[Sentence], lexicon: Lexicon, limits: Thresholds) -> list[list[Sentence]]:
    runs: list[list[Sentence]] = []
    current: list[Sentence] = []
    for sentence in [*sentences, Sentence(0, "")]:
        if sentence.text and bare_main_clause(sentence.text, lexicon, limits):
            current.append(sentence)
            continue
        if _qualifies(current, lexicon, limits):
            runs.append(current)
        current = []
    return runs


def _initials(token: str) -> bool:
    """Count z. B., d. h., e.g., and J. as initials, because none of them closes a sentence."""
    parts = token.split(".")
    return all(part.isalpha() and len(part) <= MAX_INITIAL_LETTERS for part in parts) and (len(parts) > 1 or len(token) == 1)


def ends_sentence(before: str, lexicon: Lexicon) -> bool:
    if not before.endswith("."):
        return True
    words = before[:-1].split()
    token = words[-1].lstrip(OPENING_MARKS) if words else ""
    if token.isdigit():
        return len(token) > lexicon.max_ordinal_digits
    return not (_initials(token) or token.lower() in ABBREVIATIONS)


def _code_as_word(match: re.Match[str]) -> str:
    return CODE_LETTER * len(match.group(0))


def _code_as_capital(match: re.Match[str]) -> str:
    return CODE_LETTER.upper() * len(match.group(0))


def paragraph_sentences(paragraph: Paragraph, lexicon: Lexicon) -> list[Sentence]:
    """Split on a capital copy, because a sentence may open on inline code."""
    offsets, size = [], 0
    for number, line in paragraph:
        offsets.append((size, number))
        size += len(line) + 1
    original = " ".join(line for _number, line in paragraph)
    prose = INLINE_CODE_RE.sub(_code_as_word, original)
    found, start = [], 0
    for boundary in SENTENCE_BREAK_RE.finditer(INLINE_CODE_RE.sub(_code_as_capital, original)):
        if ends_sentence(prose[start:boundary.start()], lexicon):
            found.append(Sentence(_source_line(offsets, start), prose[start:boundary.start()], original[start:boundary.start()]))
            start = boundary.end()
    if prose[start:].strip():
        found.append(Sentence(_source_line(offsets, start), prose[start:], original[start:]))
    return found


def _skipped_block(block: list[str]) -> bool:
    """Skip the block, because a list item, a nested line, or indented code is never running prose."""
    first = block[0]
    indented = len(first) - len(first.lstrip()) >= INDENTED_BLOCK
    return indented or any(LIST_ITEM_RE.match(line) for line in block)


def prose_blocks(lines: list[ProseLine]) -> Iterator[Paragraph]:
    numbers: list[int] = []
    texts: list[str] = []
    for number, line in [*lines, (0, "")]:
        if line.strip():
            numbers.append(number)
            texts.append(line)
            continue
        if texts and not _skipped_block(texts):
            yield [(row, text.strip()) for row, text in zip(numbers, texts)]
        numbers, texts = [], []


def blocks(path: str, lines: list[ProseLine]) -> list[Paragraph]:
    """One block per markup line, because a rendered page leaves no blank line between its blocks."""
    if PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS:
        return [[(number, line.strip())] for number, line in lines if line.strip()]
    return list(prose_blocks(lines))


def _lexicon_for(paragraph: Paragraph, languages: list[str]) -> Lexicon:
    number = paragraph[0][0]
    language = languages[number - 1] if 0 < number <= len(languages) else ""
    return GERMAN_LEXICON if language == GERMAN else ENGLISH


class Run(NamedTuple):
    lexicon: Lexicon
    sentences: list[Sentence]
    paragraph: list[Sentence]


def shown(sentences: list[Sentence]) -> str:
    return " ".join(sentence.shown.strip() for sentence in sentences)


def runs_in(path: str, masked: str, languages: list[str]) -> Iterator[Run]:
    """Carry the paragraph along, because a reviewer must see what surrounds the run."""
    for paragraph in blocks(path, list(_markdown_prose_lines(masked))):
        lexicon = _lexicon_for(paragraph, languages)
        sentences = paragraph_sentences(paragraph, lexicon)
        for run in bare_runs(sentences, lexicon, Thresholds()):
            yield Run(lexicon, run, sentences)


def _run_finding(path: str, run: Run) -> dict:
    return _finding(
        FAMILY, run.lexicon.rule, run.sentences[0].line,
        f"{len(run.sentences)} short main clauses in a row with nothing joining them in {path}",
        shown(run.sentences),
        ACTION,
    )


def scan_parataxis(path: str, masked: str, languages: list[str]) -> list[dict]:
    """One row per run, because the fix joins the run as a whole."""
    return [_run_finding(path, run) for run in runs_in(path, masked, languages)]
