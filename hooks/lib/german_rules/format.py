"""Stay STATIC, because each rule here matches a leftover string, link, or character, not German grammar."""
from __future__ import annotations

import re
from pathlib import PurePath

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import sentence_spans, visible
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import sentence_spans, visible
    from prose_language import ParagraphLanguage

PLACEHOLDER_TEXT = Rule(
    "de_placeholder_text",
    Wording(
        "Unfilled placeholder",
        "Flags a template slot like [Name einfügen], [Datum hier], or TODO: left in German text",
        "Fill in the real value or delete the placeholder.",
    ),
    Wording(
        "Platzhaltertext",
        "Meldet ungefüllte Platzhalter wie [Name einfügen], [Datum hier] oder TODO:",
        "Setz den echten Wert ein oder streich den Platzhalter.",
    ),
)
SEARCH_LINK_CITATION = Rule(
    "de_search_link_citation",
    Wording(
        "Search link as a source",
        "Flags a Google or DuckDuckGo search URL standing in for a real source",
        "Link the source itself or delete the link.",
    ),
    Wording(
        "Suchlink statt Quelle",
        "Meldet eine Google- oder DuckDuckGo-Suche, die als Quelle dasteht",
        "Verlinke die Quelle selbst oder streich den Link.",
    ),
)
AI_TOOL_ARTIFACT = Rule(
    "de_ai_tool_artifact",
    Wording(
        "AI tool artifact",
        "Flags a chat export leftover like oaicite, contentReference, turn0search0, [cite: 1], or a think tag",
        "Delete the artifact.",
    ),
    Wording(
        "KI-Werkzeug-Artefakt",
        "Meldet Reste aus Chat-Exporten wie oaicite, contentReference, turn0search0, [cite: 1] oder ein Think-Tag",
        "Lösch das Artefakt.",
    ),
)
ABRUPT_ENDING = Rule(
    "de_abrupt_ending",
    Wording(
        "Abrupt ending",
        "Flags German text whose last paragraph stops mid-sentence or trails off in an ellipsis",
        "Finish the sentence or delete it.",
    ),
    Wording(
        "Abrupter Abbruch",
        "Meldet Text, dessen letzter Absatz mitten im Satz oder mit Auslassungspunkten endet",
        "Schreib den Satz zu Ende oder streich ihn.",
    ),
)
DIFF_ANCHORED = Rule(
    "de_diff_anchored",
    Wording(
        "Diff-anchored wording",
        "Flags text outside a changelog or commit that narrates a change, like wurde jetzt ergänzt",
        "Describe what holds now, not what changed.",
    ),
    Wording(
        "Diff-verankertes Schreiben",
        "Meldet Text, der eine Änderung nacherzählt, etwa wurde jetzt ergänzt oder ersetzt die alte Lösung",
        "Beschreib, was jetzt gilt, nicht was sich geändert hat.",
    ),
    state="off",
)
HIDDEN_UNICODE = Rule(
    "de_hidden_unicode",
    Wording(
        "Hidden Unicode character",
        "Flags an invisible character like a zero-width space, soft hyphen, stray BOM, or bidi control",
        "Delete the invisible character.",
    ),
    Wording(
        "Versteckte Unicode-Zeichen",
        "Meldet unsichtbare Zeichen wie Nullbreiten-Leerzeichen, weiches Trennzeichen, BOM oder Bidi-Steuerzeichen",
        "Lösch das unsichtbare Zeichen.",
    ),
    state="off",
)
ENGLISH_NUMBER_FORMAT = Rule(
    "de_english_number_format",
    Wording(
        "English number or date format",
        "Flags a decimal point before a unit, like 3.5 Prozent, or an English date, like May 12, 2026",
        "Write 3,5 Prozent and 12. Mai 2026.",
    ),
    Wording(
        "Englisches Zahlen- oder Datumsformat",
        "Meldet einen Dezimalpunkt vor einer Einheit wie 3.5 Prozent oder ein englisches Datum wie May 12, 2026",
        "Schreib 3,5 Prozent und 12. Mai 2026.",
    ),
)

INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
EMOJI = r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]"
EMOJI_RE = re.compile(EMOJI)
SNIPPET_CONTEXT = 60
# humanizer-de Muster 21 triggers, because Q13 credits it.
PLACEHOLDER_RE = re.compile(
    r"\[(?:Name|Datum|Ort|Firma|Bearbeiter\s+Name|Quelle\s+erforderlich)\](?!\()"
    r"|\[[^\]\n]*\b(?:einfügen|eintragen|hier)\](?!\()|\bTODO:"
)
# humanizer-de Muster 22 hosts, because Q13 credits it.
SEARCH_LINK_RE = re.compile(r"(?i:(?:https?://)?(?:www\.)?(?:google\.[a-z.]+/search\?|duckduckgo\.com/\?)\S*)")
# humanizer-de Muster 24 tool strings, because Q13 credits it.
AI_ARTIFACT_RE = re.compile(
    r"oaicite|contentReference\[|\boai_cit(?:e|ation)\b|\b(?:cite|i)?turn\d+(?:search|image|news|file)\d+\b"
    r"|\[cite:\s*\d+(?:,\s*\d+)*\]|\[span_\d+\]\[(?:start|end)_span\]|\((?:start|end)_span\)"
    r"|\bgrok_card\b|grok_render_citation_card_json|<grok:render|【\d+†[^】]*】|\[citation:\d+\]"
    r"|\[\^\d+\^\]|_\[unsupported block: \w+\]_|</?think>|\[attached_file:\d+\]|\[web:\d+\]"
    r"|ppl-ai-file-upload|:::writing\{|\"attributableIndex\""
)
LIST_OR_BLOCK_START_RE = re.compile(r"^\s*(?:#|[-*+•]\s|\d+[.)]\s|\||>|<|!\[)")
UNFINISHED_RE = re.compile(r"(?:[^\W\d_](?:\.{3}|…)|[^\W\d_]|,)\s*$")
TRAILING_URL_RE = re.compile(r"\S*://\S*\s*$")
# humanizer-de Muster 52 phrases, because Q13 credits it.
DIFF_RE = re.compile(
    r"(?i:\bwurde\s+jetzt\b[^.!?]*?\b(?:ergänzt|erweitert|hinzugefügt|ersetzt|umgestellt)\b"
    r"|\bneu\s+hinzugefügt\b|\bersetzt\s+(?:die|den|das)\s+alte\w*|\bbisher\s+war\b[^.!?]*?\bnun\s+ist\b"
    r"|\bdie\s+überarbeitete\s+Version\b|\bmit\s+diesem\s+Update\s+wird\b)"
)
VERSIONED_NAMES = ("commit_message", "changelog", "changes", "history", "news", "release", "migrat")
# humanizer-de Muster 43 ranges, because Q13 credits it.
HIDDEN_RE = re.compile(
    "[\u200b-\u200d\u2060-\u2064\ufeff\u00ad\u202a-\u202e\u2066-\u2069\ufe00-\ufe0f"
    "\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
)
VARIATION_SELECTORS = "\ufe0e\ufe0f"
ZERO_WIDTH_JOINER = "\u200d"
BLACK_FLAG = "\U0001f3f4"
TAG_CHARACTERS = range(0xE0020, 0xE0080)
BYTE_ORDER_MARK = "\ufeff"
UNIT = (
    r"(?:Prozent|%|Euro|€|Dollar|Millionen|Milliarden|Mio\.|Mrd\.|Grad|°C|km|kg|Meter|Sekunden"
    r"|Minuten|Stunden|Tage|Jahre|GB|MB|TB|ms)"
)
ENGLISH_ONLY_MONTH = r"(?:January|February|March|May|June|July|October|December)"
ANY_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DAY = r"\d{1,2}(?:st|nd|rd|th)?"
# humanizer-de Muster 48 formats, because Q13 credits it.
NUMBER_FORMAT_RE = re.compile(
    r"(?<![\d.])\d+\.(?!\d{3}(?!\d))\d+(?![\d.])\s?" + UNIT + r"(?![A-Za-zÄÖÜäöüß])"
    r"|\b" + ANY_MONTH + r"\s+" + DAY + r",\s*\d{4}\b"
    r"|\b" + ENGLISH_ONLY_MONTH + r"\s+" + DAY + r"\b"
    r"|\b\d{1,2}\.?\s+" + ENGLISH_ONLY_MONTH + r"\b"
)


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def scannable(text: str) -> str:
    """Blank quotes and inline code at equal length, because a cited token is an example, not a leftover."""
    return INLINE_CODE_RE.sub(_blank, visible(text))


def window(paragraph: ParagraphLanguage, start: int, end: int) -> str:
    """Cut the snippet around the match, because a list or table paragraph has no sentence to quote."""
    return paragraph.text[max(0, start - SNIPPET_CONTEXT):end + SNIPPET_CONTEXT]


def pattern_hits(rule: str, paragraphs: list[ParagraphLanguage], pattern: re.Pattern[str]) -> list[Hit]:
    return [
        Hit(rule, paragraph.line, window(paragraph, found.start(), found.end()), found.group(0))
        for paragraph in paragraphs
        for found in pattern.finditer(scannable(paragraph.text))
    ]


def _abrupt_ending(paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    """Judge only the last paragraph with two sentences, because a one-line commit subject also ends without a period."""
    if not paragraphs:
        return []
    last = paragraphs[-1]
    text = visible(last.text).rstrip()
    if LIST_OR_BLOCK_START_RE.match(text) or TRAILING_URL_RE.search(text) or len(sentence_spans(text)) < 2:
        return []
    found = UNFINISHED_RE.search(text)
    if found is None:
        return []
    return [Hit(ABRUPT_ENDING.name, last.line, sentence_spans(text)[-1][1], found.group(0).strip())]


def _versioned(path: str) -> bool:
    """Exempt changelogs and commits, because there a change story is the content (humanizer-de Muster 52)."""
    return PurePath(path).name.lower().startswith(VERSIONED_NAMES)


def _in_flag(text: str, index: int) -> bool:
    start = index
    while start > 0 and ord(text[start - 1]) in TAG_CHARACTERS:
        start -= 1
    return start > 0 and text[start - 1] == BLACK_FLAG


def _emoji_at(text: str, index: int) -> bool:
    return 0 <= index < len(text) and EMOJI_RE.match(text[index]) is not None


def _allowed_hidden(paragraph: ParagraphLanguage, index: int) -> bool:
    """Keep emoji, flag, and file-start sequences, because humanizer-de Muster 43 lists them as exceptions."""
    text, char = paragraph.text, paragraph.text[index]
    if char in VARIATION_SELECTORS:
        return _emoji_at(text, index - 1) or text[index - 1:index] in "0123456789#*"
    if char == ZERO_WIDTH_JOINER:
        return (_emoji_at(text, index - 1) or text[index - 1:index] in VARIATION_SELECTORS) and _emoji_at(text, index + 1)
    if ord(char) in TAG_CHARACTERS:
        return _in_flag(text, index)
    return char == BYTE_ORDER_MARK and index == 0 and paragraph.line == 1


def _hidden_unicode(paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        Hit(HIDDEN_UNICODE.name, paragraph.line, window(paragraph, found.start(), found.end()), f"U+{ord(found.group(0)):04X}")
        for paragraph in paragraphs
        for found in HIDDEN_RE.finditer(paragraph.text)
        if not _allowed_hidden(paragraph, found.start())
    ]


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *pattern_hits(PLACEHOLDER_TEXT.name, paragraphs, PLACEHOLDER_RE),
        *pattern_hits(SEARCH_LINK_CITATION.name, paragraphs, SEARCH_LINK_RE),
        *pattern_hits(AI_TOOL_ARTIFACT.name, paragraphs, AI_ARTIFACT_RE),
        *_abrupt_ending(paragraphs),
        *([] if _versioned(path) else pattern_hits(DIFF_ANCHORED.name, paragraphs, DIFF_RE)),
        *_hidden_unicode(paragraphs),
        *pattern_hits(ENGLISH_NUMBER_FORMAT.name, paragraphs, NUMBER_FORMAT_RE),
    ]


RULE_SET = RuleSet(
    rules=(
        PLACEHOLDER_TEXT, SEARCH_LINK_CITATION, AI_TOOL_ARTIFACT, ABRUPT_ENDING,
        DIFF_ANCHORED, HIDDEN_UNICODE, ENGLISH_NUMBER_FORMAT,
    ),
    check=_check,
)
