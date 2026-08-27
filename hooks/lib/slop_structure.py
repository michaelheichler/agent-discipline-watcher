from __future__ import annotations

import re
from typing import NamedTuple, cast

try:
    from .comment_rules import _finding
    from .findings import FindingDict
    from .prose_structure import _markdown_prose_lines
except ImportError:
    from comment_rules import _finding
    from findings import FindingDict
    from prose_structure import _markdown_prose_lines


class StructureRule(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    detail: str
    action: str


_BINARY_CONTRAST_RE = re.compile(
    r"\bnot\s+because\b[^.!?\n]{0,80}?[.,]\s*(?:but\s+)?because\b"
    r"|\b(?:is|are|was|were)n[''`]?t\s+the\s+(?:problem|point|issue|question|answer)\b"
    r"|\bthe\s+(?:question|answer|problem|point)\s+is\s*n[''`]?t\b"
    r"|\bit\s+(?:feels|looks|seems)\s+like\b[^.!?\n]{0,60}?\.\s*(?:it[''`]?s|that[''`]?s)\s+(?:actually|really)\b"
    r"|\bit[''`]?s\s+not\s+[^.!?\n]{0,60}?,\s*it[''`]?s\b"
    r"|\bstops?\s+being\b[^.!?\n]{0,40}?\band\s+starts?\s+being\b"
    r"|\bnot\s+just\b[^.!?\n]{0,60}?\bbut\s+also\b"
    r"|\bdoes\s*n[''`]?t\s+mean\b[^.!?\n]{0,60}?\bbut\s+(?:actually|really)\b",
    re.IGNORECASE,
)
_NEGATIVE_LISTING_RE = re.compile(
    r"\b(?:it\s+)?(?:was|is)\s*n[''`]?t\s+[^.!?\n]{0,50}?\.\s*"
    r"(?:it\s+)?(?:was|is)\s*n[''`]?t\s+[^.!?\n]{0,50}?\.\s*"
    r"(?:it\s+)?(?:was|is)\b"
    r"|\bnot\s+an?\s+[^.!?\n]{0,40}?\.{2,}\s*not\s+an?\b",
    re.IGNORECASE,
)
_DRAMATIC_FRAGMENT_RE = re.compile(
    r"\.\s*That[''`]?s\s+it\.\s*That[''`]?s\s+the\b"
    r"|\bThis\s+unlocks\s+something\b"
    r"|^\s*[A-Z][\w-]*\.\s+And\s+[\w-]+\.\s+And\s+[\w-]+\.",
)
_FORMULAIC_CONSTRUCTION_RE = re.compile(
    r"\bby\s+the\s+time\b[^.!?\n]{0,60}?,\s*(?:i|we|they|he|she|it)\s+(?:was|were|had)\b"
    r"|\b\w+\s+that\s+is\s*n[''`]?t\s+\w+",
    re.IGNORECASE,
)
_FALSE_AGENCY_RE = re.compile(
    r"\b(?:a|the)\s+(?:complaint|decision|culture|conversation|data|market|"
    r"history|silence|nature|technology|evidence|system|process|team|company)\s+"
    r"(?:often\s+)?(?:becomes?|emerges?|shifts?|moves?\s+toward|tells?\s+us|rewards?|"
    r"lives?\s+or\s+dies|speaks?|says|demands?|refuses?|remembers?|decides?|"
    r"wants?|knows?|believes?|repeats?)\b",
    re.IGNORECASE,
)
_NARRATOR_DISTANCE_RE = re.compile(
    r"\b(?:(?:some|many|most)\s+people|people)\s+"
    r"(?:believe|think|say|argue|claim|tend\s+to)\b"
    r"|^\s*Nobody\s+(?:designed|planned|chose|decided|wanted)\b"
    r"|^\s*This\s+(?:is\s+why|happens\s+because)\b",
    re.IGNORECASE,
)
# Listed because an ed or en suffix test is blind to the irregular participles, which carried 10 of 13 real passives in a tracked sample.
_IRREGULAR_PARTICIPLES = (
    "built", "sent", "kept", "lost", "told", "caught", "taught", "brought", "bought",
    "thought", "sought", "set", "read", "held", "made", "put", "cut", "split", "shut",
    "hit", "let", "left", "found", "met", "paid", "said", "sold", "spent", "won",
    "hurt", "felt", "dealt", "meant", "heard", "led", "fed", "run", "understood",
)
_PASSIVE_VOICE_RE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being)\s+(?:being\s+)?"
    r"(?:[a-z]+(?:ed|en)|(?:re|un|over|under|mis|out)?(?:" + "|".join(_IRREGULAR_PARTICIPLES) + r"))\b"
    r"|\b(?:mistakes|errors|decisions|choices|changes|promises)\s+(?:were|was)\s+made\b"
    r"|\bit\s+is\s+believed\s+that\b",
    re.IGNORECASE,
)
_RHETORICAL_SETUP_RE = re.compile(
    r"\b(?:have\s+you\s+ever\s+wondered|here[''`’]?s\s+what\s+i\s+mean"
    r"|think\s+about\s+it|and\s+that[''`’]?s\s+okay)\b"
    r"|^\s*What\s+if\s+[^?\n]{5,80}\?",
    re.IGNORECASE,
)
# Wh- openers and "So"/"Look," starts are a named stop-slop pattern, kept apart because they judge position rather than wording.
_WEAK_STARTER_RE = re.compile(
    r"^\s*(?:What|When|Where|Which|Who|Why|How)\b[^?\n]{5,}\?"
    r"|^\s*So\s+[a-z]"
    r"|^\s*Look,\s",
)
_LAZY_EXTREME_RE = re.compile(
    r"\b(?:every\s+single|everyone\s+(?:knows|agrees)|nobody\s+(?:ever|wants)"
    r"|always\s+(?:has|have|been)|never\s+(?:once|ever))\b"
    r"|\bevery\s+\w+\s+always\b"
    r"|\b(?:everyone|everybody|nobody)\s+\w+\s+(?:always|never|every)\b",
    re.IGNORECASE,
)

STRUCTURE_CANDIDATES = (
    StructureRule(
        "binary_contrast",
        _BINARY_CONTRAST_RE,
        "Formulaic negation and reversal",
        "State the positive claim directly.",
    ),
    StructureRule(
        "formulaic_construction",
        _FORMULAIC_CONSTRUCTION_RE,
        "Formulaic relative-clause negation",
        "Replace the template with a direct description.",
    ),
    StructureRule(
        "false_agency",
        _FALSE_AGENCY_RE,
        "An abstraction receives human agency",
        "Name the person or action responsible.",
    ),
    StructureRule(
        "narrator_distance",
        _NARRATOR_DISTANCE_RE,
        "The narrator generalizes about unnamed people",
        "Name the people or address the reader directly.",
    ),
    StructureRule(
        "passive_voice",
        _PASSIVE_VOICE_RE,
        "Passive voice hides the actor",
        "Name the actor and use an active verb.",
    ),
    StructureRule(
        "rhetorical_setup",
        _RHETORICAL_SETUP_RE,
        "A rhetorical setup delays the claim",
        "Remove the setup and state the claim.",
    ),
    StructureRule(
        "negative_listing",
        _NEGATIVE_LISTING_RE,
        "Accumulated negations build to a reveal",
        "Assert the point without the runway.",
    ),
    StructureRule(
        "dramatic_fragmentation",
        _DRAMATIC_FRAGMENT_RE,
        "Sentence fragments manufacture emphasis",
        "Write complete sentences.",
    ),
    StructureRule(
        "weak_sentence_starter",
        _WEAK_STARTER_RE,
        "Sentence opens on a question word or a filler start",
        "Lead with the subject or the verb.",
    ),
    StructureRule(
        "lazy_extreme",
        _LAZY_EXTREME_RE,
        "An absolute stands in for a specific claim",
        "Name the actual scope or number.",
    ),
)
STRUCTURE_RULES: tuple[StructureRule, ...] = STRUCTURE_CANDIDATES
# Empty because the earlier omissions rested on an AI versus human separation test, which measures the wrong property for a named pattern.
OMITTED_STRUCTURE_RULES: dict[str, str] = {}


def _line_findings(path: str, line_number: int, line: str) -> list[FindingDict]:
    return [
        cast(
            FindingDict,
            _finding(
                "english",
                rule.name,
                line_number,
                rule.detail + " in " + path,
                line,
                rule.action,
            ),
        )
        for rule in STRUCTURE_RULES
        if rule.pattern.search(line)
    ]


def _scan_slop_structure(path: str, text: str) -> list[FindingDict]:
    findings: list[FindingDict] = []
    for line_number, line in _markdown_prose_lines(text):
        findings.extend(_line_findings(path, line_number, line))
    return findings
