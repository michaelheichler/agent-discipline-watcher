"""German prose follows Duden typography, because the English dash, colon, and semicolon bans misfire on correct German."""
from __future__ import annotations

import re

try:
    from .findings import Finding
    from .prose_language import GERMAN
except ImportError:
    from findings import Finding
    from prose_language import GERMAN

# Kept because T-010 has not measured them yet.
DASH_CLUSTER_MIN_COUNT = 5
DASH_CLUSTER_MIN_PER_1000_WORDS = 15.0

ENGLISH_ONLY_RULES = frozenset({"prose_semicolon", "prose_colon"})
GEDANKENSTRICH_RE = re.compile("(?:^|(?<=\\s))\u2013(?=\\s|$)")
BIS_STRICH_RE = re.compile("(?<=\\d)\u2013(?=\\d)")
GERMAN_QUOTED_RE = re.compile("\u201e[^\u201e\u201c\u201d\\n]*\u201c|\u201a[^\u201a\u2018\u2019\\n]*\u2018")
WRONG_QUOTE_RE = re.compile("[\"\u201c\u201d\u2018]|(?<!\\w)'[^'\\n]+'(?!\\w)")
GENITIVE_APOSTROPHE_RE = re.compile("(?<=[\\w,] )[A-Z\u00c4\u00d6\u00dc][a-z\u00e4\u00f6\u00fc\u00df]+['\u2019]s\\b")
TYPED_ELLIPSIS_RE = re.compile("\\.{3,}|\u2026\\.|\\.\u2026")
WORD_RE = re.compile(r"[^\W\d_]+")

GERMAN_RULES = (
    ("prose", (WRONG_QUOTE_RE,), "quote_marks",
     "Quote marks do not follow German typography in ", "Use the German pairs „…“ or ‚…‘."),
    ("prose", (GENITIVE_APOSTROPHE_RE,), "genitive_apostrophe",
     "English genitive apostrophe in ", "Write the genitive s without an apostrophe."),
    ("prose", (TYPED_ELLIPSIS_RE,), "typed_ellipsis",
     "Ellipsis typed as periods in ", "Use one … character with no extra period."),
)


def german_rules(english_rules: tuple) -> tuple:
    """Drop the colon and semicolon bans, because German uses both marks as ordinary connectors."""
    kept = tuple(row for row in english_rules if row[2] not in ENGLISH_ONLY_RULES)
    return kept + GERMAN_RULES


def german_view(clean: str) -> str:
    """Blank the Gedankenstrich, the Bis-Strich, and German quoted spans, because all three are correct Duden typography."""
    without_dashes = BIS_STRICH_RE.sub(" ", GEDANKENSTRICH_RE.sub(" ", clean))
    return GERMAN_QUOTED_RE.sub(lambda found: " " * len(found.group(0)), without_dashes)


def _is_cluster(dashes: int, words: int) -> bool:
    dense = dashes * 1000 > DASH_CLUSTER_MIN_PER_1000_WORDS * words
    return dashes >= DASH_CLUSTER_MIN_COUNT and dense


def dash_cluster_findings(path: str, lines: list[str], languages: list[str]) -> list[dict]:
    """Count the whole document, because one Gedankenstrich is correct and only a pile of them reads as generated."""
    german = [(number, line) for number, (line, language) in enumerate(zip(lines, languages), 1) if language == GERMAN]
    dash_lines = [number for number, line in german for _ in GEDANKENSTRICH_RE.finditer(line)]
    words = sum(len(WORD_RE.findall(line)) for _, line in german)
    if not _is_cluster(len(dash_lines), words):
        return []
    first = dash_lines[0]
    return [Finding(
        family="punctuation", rule="dash_cluster", line=first,
        detail=f"{len(dash_lines)} spaced dashes in {words} German words in {path}",
        force=True, snippet=lines[first - 1].strip()[:180],
        action="Replace some dashes with a comma, period, or colon.",
        path=None, severity=None, tool_use_id=None, match="\u2013", language=GERMAN,
    ).to_dict()]
