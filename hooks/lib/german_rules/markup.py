"""Stay STATIC, because each rule here reads Markdown structure a chatbot sets for looks rather than meaning."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from .format import EMOJI, pattern_hits, scannable
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules.format import EMOJI, pattern_hits, scannable
    from prose_language import ParagraphLanguage

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
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
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
# humanizer-de Muster 57 cases A to C, because Q13 credits it.
THEMATIC_BREAK = r"(?:-{3,}|\*{3,}|_{3,})"
BREAK_THEN_HEADING_RE = re.compile(r"^" + THEMATIC_BREAK + r"\s+#{1,6}\s")
BREAK_ONLY_RE = re.compile(r"^" + THEMATIC_BREAK + r"$")
NEXT_PARAGRAPH_GAP = 2
SEPARATOR_ROW_RE = re.compile(r"\|(?:\s*:?-{3,}:?\s*\|)+")
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")
PIPE_RE = re.compile(r"(?<!\\)\|")
ONE_DATA_ROW_TABLE_ROWS = 3


def _heading(text: str) -> re.Match[str] | None:
    return HEADING_RE.match(text)


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
    found = _heading(text)
    if found is None or text.endswith(SENTENCE_END):
        return []
    word = _title_word(found.group(2))
    return [] if word is None else [Hit(ENGLISH_TITLE_CASE.name, paragraph.line, paragraph.text, word)]


def _bare_items(text: str) -> list[str]:
    start = LIST_START_RE.search(text)
    if start is None:
        return []
    items = [item.strip() for item in ITEM_SPLIT_RE.split(text[start.end():])]
    return [item for item in items if BARE_KEYWORD_RE.match(item) and item.split()[-1] not in ABBREVIATIONS]


def _bullet_punctuation(paragraph: ParagraphLanguage) -> list[Hit]:
    """Wait for two such items, because humanizer-de flags the list habit, not one short sentence."""
    bare = _bare_items(scannable(paragraph.text))
    if len(bare) < MIN_BARE_ITEMS:
        return []
    return [Hit(BULLET_PUNCTUATION.name, paragraph.line, item, item) for item in bare]


def _one_row_table(paragraph: ParagraphLanguage) -> list[Hit]:
    """Count pipes per row, because the scanner joins a table's lines with spaces."""
    text = scannable(paragraph.text)
    separator = SEPARATOR_ROW_RE.search(text)
    if not text.startswith("|") or separator is None:
        return []
    width = len(SEPARATOR_CELL_RE.findall(separator.group(0))) + 1
    if len(PIPE_RE.findall(text)) != width * ONE_DATA_ROW_TABLE_ROWS:
        return []
    return [Hit(MARKDOWN_ARTIFACT.name, paragraph.line, paragraph.text, separator.group(0))]


def _skipped_levels(paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    hits, previous = [], 0
    for paragraph in paragraphs:
        found = _heading(paragraph.text)
        level = len(found.group(1)) if found else 0
        if level > previous + 1 and previous:
            hits.append(Hit(MARKDOWN_ARTIFACT.name, paragraph.line, paragraph.text, "#" * level))
        previous = level or previous
    return hits


def _break_before_heading(paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    """Check both layouts, because a blank line between rule and heading splits them into two paragraphs."""
    split = [
        Hit(MARKDOWN_ARTIFACT.name, before.line, after.text, before.text)
        for before, after in zip(paragraphs, paragraphs[1:])
        if BREAK_ONLY_RE.match(before.text) and _heading(after.text)
        and after.line - before.line <= NEXT_PARAGRAPH_GAP
    ]
    return [*split, *pattern_hits(MARKDOWN_ARTIFACT.name, paragraphs, BREAK_THEN_HEADING_RE)]


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
