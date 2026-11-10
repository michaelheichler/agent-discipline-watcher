# SPDX-FileCopyrightText: Martin Moeller, humanizer-de trigger lists (see NOTICE)
# SPDX-License-Identifier: MIT AND CC-BY-SA-4.0
"""Stay STATIC, because each rule here reads Markdown structure a chatbot sets for looks rather than meaning."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import Span, placed, line_units
    from .format import EMOJI, pattern_hits, scannable
    from ..prose_language import ParagraphLanguage
    from ..markup import BREAK_THEN_HEADING_RE, BREAK_ONLY_RE, markdown_heading, one_row_table_separator
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import Span, placed, line_units
    from german_rules.format import EMOJI, pattern_hits, scannable
    from prose_language import ParagraphLanguage
    from markup import BREAK_THEN_HEADING_RE, BREAK_ONLY_RE, markdown_heading, one_row_table_separator

FAKE_BULLET = Rule(
    "de_fake_bullet",
    Wording(
        "Fake list bullet",
        "Flags a typed bullet glyph like • as a list marker, which Markdown renders as plain text",
        "Start each list item with a hyphen.",
    ),
    Wording(
        "Falsches Listenzeichen",
        "Meldet ein getipptes Aufzählungszeichen wie •, das Markdown als Fließtext zeigt",
        "Beginn jeden Stichpunkt mit einem Bindestrich.",
    ),
)
EMOJI_HEADING = Rule(
    "de_emoji_heading",
    Wording(
        "Emoji before a heading",
        "Flags a heading or a short label line that opens with an emoji, like 🎓 Bildung",
        "Delete the emoji.",
    ),
    Wording(
        "Emoji vor Überschrift",
        "Meldet eine Überschrift oder kurze Zeile, die mit einem Emoji beginnt, etwa 🎓 Bildung",
        "Streich das Emoji.",
    ),
)
ENGLISH_TITLE_CASE = Rule(
    "de_english_title_case",
    Wording(
        "English title case",
        "Flags a German heading that capitalizes articles, prepositions, or adjectives, like Die Neue KI Strategie",
        "Capitalize only the first word and the nouns.",
    ),
    Wording(
        "Englische Titel-Großschreibung",
        "Meldet Überschriften mit großgeschriebenen Artikeln, Präpositionen oder Adjektiven wie Die Neue KI Strategie",
        "Schreib nur das erste Wort und die Substantive groß.",
    ),
)
BULLET_PUNCTUATION = Rule(
    "de_bullet_punctuation",
    Wording(
        "Period after bare bullet keywords",
        "Flags a German list whose one- or two-word keyword items end in a period",
        "Drop the period after a bare keyword.",
    ),
    Wording(
        "Punkt hinter Stichwort",
        "Meldet Listen, deren Stichwörter aus einem oder zwei Wörtern mit einem Punkt enden",
        "Lass den Punkt hinter dem Stichwort weg.",
    ),
)
MARKDOWN_ARTIFACT = Rule(
    "de_markdown_artifact",
    Wording(
        "Decorative Markdown structure",
        "Flags a table with one data row, a skipped heading level like H2 to H4, or a horizontal rule right above a heading",
        "Write the table as a sentence, step headings down one level at a time, and drop the rule.",
    ),
    Wording(
        "Markdown-Struktur-Artefakt",
        "Meldet Tabellen mit einer Datenzeile, übersprungene Überschriftenebenen und Trennlinien über Überschriften",
        "Schreib die Tabelle als Satz, steig eine Ebene nach der anderen ab und streich die Trennlinie.",
    ),
)

# humanizer-de Muster 14 glyphs, because Q13 credits it.
FAKE_BULLET_RE = re.compile(r"(?:^|(?<=:\s))[•▪◦‣](?=\s)")
EMOJI_PRESENTATION = chr(0xFE0F)
# humanizer-de Muster 15, because Q13 credits it.
EMOJI_HEADING_RE = re.compile(r"^#{1,6}\s*" + EMOJI + r"|^" + EMOJI + EMOJI_PRESENTATION + r"?\s+\S+(?:\s+\S+){0,3}$")
SENTENCE_END = (".", "!", "?")
# humanizer-de Muster 47, because Q13 credits it.
FUNCTION_WORDS = frozenset(
    "Der Die Das Dem Den Des Ein Eine Einen Einem Einer Eines Und Oder Für Von Vom Mit Im In Ins Auf Zu Zur Zum "
    "Über Unter Bei Beim Nach Aus Am An Ohne Gegen Durch Als Wie".split()
)
TITLE_ADJECTIVE_RE = re.compile(
    r"\b(?:[Dd](?:er|ie|as|em|en|es)|[Ee]ine?[mnrs]?)\s+([A-ZÄÖÜ][a-zäöüß]+(?:e|en|er|es|em))\s+[A-ZÄÖÜ]"
)
LIST_START_RE = re.compile(r"(?:^|:\s+)[-*+]\s+")
ITEM_SPLIT_RE = re.compile(r"\s[-*+]\s+")
# humanizer-de Muster 50 bare keyword, because Q13 credits it.
BARE_KEYWORD_RE = re.compile(r"^[^\s.]+(?:\s[^\s.]+)?\.$")
ABBREVIATIONS = frozenset({"usw.", "etc.", "bzw.", "Nr.", "ca.", "evtl.", "ggf.", "inkl.", "vgl."})
MIN_BARE_ITEMS = 2
NEXT_PARAGRAPH_GAP = 2
def _title_word(heading: str) -> str | None:
    """Spare the word after a colon, because a German subtitle starts a new sentence."""
    words = heading.replace(":", " : ").split()
    for previous, word in zip(words, words[1:]):
        if word in FUNCTION_WORDS and previous != ":":
            return word
    found = TITLE_ADJECTIVE_RE.search(heading)
    return found.group(1) if found else None


def _title_case(paragraph: ParagraphLanguage) -> list[Hit]:
    """Skip a paragraph ending in a period, because then a body sentence follows the heading on the next line."""
    text = scannable(paragraph.text).rstrip()
    found = markdown_heading(text)
    if found is None or text.endswith(SENTENCE_END):
        return []
    word = _title_word(found.group(2))
    return [] if word is None else [Hit(ENGLISH_TITLE_CASE.name, paragraph.line, paragraph.text, word)]


def _items(text: str, start: int) -> list[tuple[Span, str]]:
    bounds = [start, *(found for split in ITEM_SPLIT_RE.finditer(text, start) for found in split.span())]
    pieces = zip(bounds[::2], [*bounds[1::2], len(text)])
    return [((low, high), text[low:high].strip()) for low, high in pieces]


def _bare_items(text: str) -> list[tuple[Span, str]]:
    start = LIST_START_RE.search(text)
    if start is None:
        return []
    return [
        (span, item) for span, item in _items(text, start.end())
        if BARE_KEYWORD_RE.match(item) and item.split()[-1] not in ABBREVIATIONS
    ]


def _bullet_punctuation(paragraph: ParagraphLanguage) -> list[Hit]:
    """Wait for two such items, because humanizer-de flags the list habit, not one short sentence."""
    bare = _bare_items(scannable(paragraph.text))
    if len(bare) < MIN_BARE_ITEMS:
        return []
    return [placed(paragraph, span, Hit(BULLET_PUNCTUATION.name, paragraph.line, item, item)) for span, item in bare]


def _one_row_table(paragraph: ParagraphLanguage) -> list[Hit]:
    """Count pipes per row, because the scanner joins a table's lines with spaces."""
    text = scannable(paragraph.text)
    separator = one_row_table_separator(text)
    if separator is None:
        return []
    return [Hit(MARKDOWN_ARTIFACT.name, paragraph.line, paragraph.text, separator.group(0), paragraph.end_line)]


def _skipped_levels(paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    hits, previous = [], 0
    for paragraph in paragraphs:
        for offset, text in line_units(paragraph):
            found = markdown_heading(text)
            level = len(found.group(1)) if found else 0
            if level > previous + 1 and previous:
                hits.append(placed(paragraph, (offset + found.start(1), offset + found.end(1)),
                                   Hit(MARKDOWN_ARTIFACT.name, paragraph.line, text, "#" * level)))
            previous = level or previous
    return hits


def _break_before_heading(paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    """Check both layouts, because a blank line between rule and heading splits them into two paragraphs."""
    lines = [(paragraph, offset, text) for paragraph in paragraphs for offset, text in line_units(paragraph)]
    split = []
    for (before, offset, text), (after, next_offset, following) in zip(lines, lines[1:]):
        line = before.lines_of(offset, offset + len(text))[0]
        next_line = after.lines_of(next_offset, next_offset + len(following))[0]
        if BREAK_ONLY_RE.fullmatch(text.strip()) and markdown_heading(following.strip()):
            if next_line - line <= NEXT_PARAGRAPH_GAP:
                split.append(placed(before, (offset, offset + len(text)),
                                    Hit(MARKDOWN_ARTIFACT.name, line, following, text)))
    combined = [*split, *pattern_hits(MARKDOWN_ARTIFACT.name, paragraphs, BREAK_THEN_HEADING_RE)]
    return list({(hit.line, hit.match.strip()): hit for hit in combined}.values())


def _each(paragraphs: list[ParagraphLanguage], judge) -> list[Hit]:
    return [hit for paragraph in paragraphs for hit in judge(paragraph)]


def _check(_path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *pattern_hits(FAKE_BULLET.name, paragraphs, FAKE_BULLET_RE),
        *pattern_hits(EMOJI_HEADING.name, paragraphs, EMOJI_HEADING_RE),
        *_each(paragraphs, _title_case),
        *_each(paragraphs, _bullet_punctuation),
        *_each(paragraphs, _one_row_table),
        *_skipped_levels(paragraphs),
        *_break_before_heading(paragraphs),
    ]


RULE_SET = RuleSet(
    rules=(FAKE_BULLET, EMOJI_HEADING, ENGLISH_TITLE_CASE, BULLET_PUNCTUATION, MARKDOWN_ARTIFACT),
    check=_check,
)
