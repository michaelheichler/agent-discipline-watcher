from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import NamedTuple, cast

try:
    from .findings import Finding, FindingDict
    from .markup import _strip_english_hidden, _strip_inline_code, mask_phrase_mentions
    from .prose_structure import _markdown_prose_lines
except ImportError:
    from findings import Finding, FindingDict
    from markup import _strip_english_hidden, _strip_inline_code, mask_phrase_mentions
    from prose_structure import _markdown_prose_lines


LiteralCheck = Callable[[str, re.Match[str]], bool]
APOSTROPHE_TRANSLATION = str.maketrans({"’": "'", "‘": "'", "`": "'"})
TECHNICAL_OBJECT_RE = re.compile(
    r"\b(?:archive|tarball|zip|tuple|bytes?|buffer|packet|struct|payload|route|routing|"
    r"directory|file|syntax|menu|tree|graph|path|parser|stream|BOM|UTF-8|"
    r"cache|value|descriptor|socket|process|destination|storage|record|row|node|page|entry)\b"
    r"|\b\w+\([^\n)]*\)|\b\d+(?:\.\d+)?\b|(?:\.?\.?/)[\w./-]+",
    re.IGNORECASE,
)
MEASURABLE_PROPERTY_RE = re.compile(
    r"(?:fast|slow|deterministic|reliable|secure|portable|readable|thread-safe)", re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PhraseFamily:
    patterns: tuple[re.Pattern[str], ...]
    literal: LiteralCheck | None = None

    @classmethod
    def compile(cls, *patterns: str, literal: LiteralCheck | None = None) -> PhraseFamily:
        return cls(tuple(re.compile(pattern, re.I) for pattern in patterns), literal)


def phrase_text(text: str) -> str:
    """Normalize once because every phrase rule scans the same visible text."""
    return mask_phrase_mentions(text).translate(APOSTROPHE_TRANSLATION)


def _literal_use(text: str) -> bool:
    return bool(TECHNICAL_OBJECT_RE.search(text) or MEASURABLE_PROPERTY_RE.fullmatch(text.strip()))


class EnglishRule(NamedTuple):
    family: PhraseFamily
    name: str
    action: str


class WeightedMarker(NamedTuple):
    phrase: str
    weight: int


class PhraseMatch(NamedTuple):
    phrase: str
    weight: float
    start: int


class ScanText(NamedTuple):
    path: str
    source: str
    visible: str


class FindingMatch(NamedTuple):
    rule: str
    match: PhraseMatch
    density: float | None


class PositiveCounts(NamedTuple):
    true_positive: int
    predicted_positive: int


class RuleEvidence(NamedTuple):
    corpus: str
    sample_size: int
    counts: PositiveCounts

    @property
    def precision(self) -> float:
        return self.counts.true_positive / self.counts.predicted_positive


WEIGHTED_MARKERS = (
    WeightedMarker("delve", 3),
    WeightedMarker("ever-evolving", 3),
    WeightedMarker("thought-provoking", 3),
    WeightedMarker("in today's rapidly evolving", 3),
    WeightedMarker("foster", 2),
    WeightedMarker("pivotal", 2),
    WeightedMarker("nuanced", 2),
    WeightedMarker("robust", 2),
    WeightedMarker("holistic", 2),
    WeightedMarker("synergy", 2),
    WeightedMarker("paradigm", 2),
    WeightedMarker("encompass", 2),
    WeightedMarker("intricate", 2),
    WeightedMarker("comprehensive", 2),
    WeightedMarker("underscores", 2),
    WeightedMarker("underscore", 2),
    WeightedMarker("cornerstone", 2),
    WeightedMarker("underpinning", 2),
    WeightedMarker("facilitating", 2),
    WeightedMarker("harnessing", 2),
    WeightedMarker("spearheading", 2),
    WeightedMarker("revolutionize", 2),
    WeightedMarker("cutting-edge", 2),
    WeightedMarker("deep dive", 2),
    WeightedMarker("at the forefront", 2),
    WeightedMarker("at its core", 2),
    WeightedMarker("it is crucial", 2),
    WeightedMarker("it is essential", 2),
    WeightedMarker("plays a crucial role", 2),
    WeightedMarker("crucial", 1),
    WeightedMarker("enhance", 1),
    WeightedMarker("innovative", 1),
    WeightedMarker("streamline", 1),
    WeightedMarker("optimize", 1),
    WeightedMarker("elevate", 1),
    WeightedMarker("empower", 1),
    WeightedMarker("stakeholder", 1),
    WeightedMarker("ecosystem", 1),
    WeightedMarker("actionable", 1),
    WeightedMarker("seamless", 1),
    WeightedMarker("seamlessly", 1),
    WeightedMarker("furthermore", 1),
    WeightedMarker("moreover", 1),
    WeightedMarker("consequently", 1),
    WeightedMarker("nevertheless", 1),
    WeightedMarker("in essence", 1),
    WeightedMarker("having said that", 1),
    WeightedMarker("that being said", 1),
    WeightedMarker("with that in mind", 1),
    WeightedMarker("in this context", 1),
    WeightedMarker("in light of", 1),
    WeightedMarker("as we navigate", 1),
    WeightedMarker("it goes without saying", 1),
    WeightedMarker("the bottom line", 1),
    WeightedMarker("key takeaway", 1),
    WeightedMarker("food for thought", 1),
    WeightedMarker("resonate", 1),
    WeightedMarker("aligns with", 1),
    WeightedMarker("bolster", 1),
    WeightedMarker("catalyst", 1),
    WeightedMarker("arguably", 1),
    WeightedMarker("notably", 1),
    WeightedMarker("specifically", 1),
    WeightedMarker("essentially", 1),
    WeightedMarker("fundamentally", 1),
    WeightedMarker("inherently", 1),
    WeightedMarker("intricacies", 1),
)

FORMULAIC_OPENERS = (
    r"in (?:the|a) (?:world|era|age|landscape) (?:where|of|that)",
    r"(?:are you |ever )?(?:looking|wondering|struggling|trying) to",
    r"(?:imagine|picture) (?:this|a world)",
    r"(?:whether you'?re|if you'?re) (?:a |an )?(?:seasoned|beginner|new)",
    r"(?:in|throughout) (?:recent years|the past decade|today'?s society)",
    r"(?:it'?s no (?:secret|surprise)|there'?s no denying) that",
    r"as (?:technology|the world|we|society) continues to",
    r"the (?:rise|emergence|advent|proliferation) of",
)
FORMULAIC_CLOSERS = (
    r"in conclusion,?",
    r"(?:in summary|to summarize|to sum up),?",
    r"(?:ultimately|at the end of the day),?",
    r"as we (?:navigate|move forward|look ahead|continue)",
    r"(?:the (?:future|road ahead) (?:is|looks|holds))",
    r"(?:by|through) (?:embracing|leveraging|harnessing|adopting)",
    r"(?:only time will tell|the possibilities are (?:endless|limitless))",
    r"(?:it'?s clear|one thing is (?:clear|certain)) that",
    r"(?:in this ever|in our ever|in an ever)",
    r"(?:remember|keep in mind),? (?:it'?s|the)",
)
FILLER_PATTERNS = (
    r"(?:it is|it's) worth (?:noting|remembering|mentioning|highlighting|considering|understanding|recognizing)",
    r"it is (?:important|worth|crucial|essential|interesting) to (?:note|remember|mention|highlight|consider|understand|recognize)",
    r"on (?:the )?one hand\b.{3,120}\bon the other(?: hand)?",
    r"(?:this|that|which) (?:is to say|means that|implies that|suggests that|indicates that)",
    r"(?:first and foremost|last but not least)",
    r"(?:without (?:a )?doubt|beyond (?:a )?shadow of (?:a )?doubt)",
)
THROAT_CLEARING_PATTERNS = (
    r"here'?s (?:the thing|what|this|that|why)\b",
    r"the uncomfortable truth is",
    r"\bit turns out\b",
    r"the real \w+ is\b",
    r"let me be clear",
    r"the truth is,",
    r"i'?ll say it again:",
    r"i'?m going to be honest",
    r"can we talk about",
)
EMPHASIS_CRUTCH_PATTERNS = (
    r"^\s*(?:full stop|period)\.",
    r"let that sink in",
    r"\bthis matters because\b",
    r"make no mistake",
    r"here'?s why that matters",
)
META_COMMENTARY_PATTERNS = (
    r"^\s*(?:hint|plot twist|spoiler):",
    r"you already know this,? but",
    r"but that'?s another (?:post|story)",
    r"\bis a feature,? not a bug\b",
    r"\bdressed up as\b",
    r"the rest of this (?:essay|post|article)",
    r"let me walk you through",
    r"in this section,? we'?ll",
    r"as we'?ll see",
    r"i want to explore",
)
TELLING_PATTERNS = (
    r"this is genuinely hard",
    r"this is what \w+ actually looks like",
    r"\bactually matters\b",
)
VAGUE_DECLARATIVE_PATTERNS = (
    r"the reasons are structural",
    r"the implications are significant",
    r"this is the deepest problem",
    r"the stakes are high",
    r"the consequences are real",
    r"the (?:challenges|issues|problems) are (?:multifaceted|complex)"
    r" and the (?:opportunities|possibilities) are (?:transformative|limitless|endless)",
)
PERFORMATIVE_PATTERNS = (
    r"\bcreeps in\b",
    r"\bthey exist,? i promise\b",
    r"\bi promise\b",
)
BANNED_ADVERB_PATTERNS = (
    r"\b(?:really|just|literally|genuinely|honestly|simply|actually|deeply|truly"
    r"|fundamentally|inherently|inevitably|interestingly|importantly|crucially"
    r"|absolutely|totally|completely|utterly|entirely)\b",
)
JARGON_PATTERNS = (
    r"\bnavigat(?:e|ed|ing|es) the\b",
    r"\b(?:explor(?:e|es|ed|ing)|examin(?:e|es|ed|ing)) (?:this|the) "
    r"(?:complicated|complex|wider|broader|evolving) (?:\w+ ){0,2}(?:environment|ecosystem|landscape)\b",
    r"\bembrac(?:e|es|ed|ing) (?:the|a|our) (?:new |evolving )?strategic (?:direction|vision|paradigm)\b",
    r"\b(?:let me |to )?unpack (?:the|this|that)\b",
    r"\blean(?:s|ing)? into\b",
    r"\b(?:competitive|market|business|digital|regulatory|technology|tech|threat|security|cybersecurity|vendor"
    r"|industry|political|media|funding|startup|investment|product|talent|economic|financial|corporate"
    r"|enterprise|software|ai|data|cloud|crypto|compliance|policy|geopolitical|entertainment|retail|healthcare"
    r"|marketing|cultural|social|educational|legal|moral|cryptocurrency|television|streaming|gaming) landscape\b",
    r"\bthe (?:current|changing|evolving|shifting|ever-changing|modern|broader|wider) landscape\b",
    r"\btoday'?s landscape\b",
    r"\bthe landscape (?:(?:has|is) (?:been )?(?:chang|shift|evolv)\w*|shifted|changed|evolved)\b",
    r"\bdoubl(?:e|ing) down on\b",
    r"\ba deep dive\b",
    r"\btake a step back\b",
    r"\bmoving forward\b",
)
EXTRA_FILLER_PATTERNS = (
    r"\bat its core\b",
    r"\bin today'?s \w+",
    r"\bwhen it comes to\b",
    r"\bthe reality is\b",
)
WEIGHTED_DENSITY_THRESHOLD = 20.0
MINIMUM_WEIGHTED_MATCHES = 3
RULE_SCOPES = {
    "weighted_slop_marker": "document",
    "formulaic_opener": "document",
    "formulaic_filler": "document",
}
RULE_EVIDENCE = (
    (
        "weighted_slop_marker",
        RuleEvidence("AI Generated Essays Dataset.csv", 40, PositiveCounts(2, 2)),
    ),
    (
        "formulaic_opener",
        RuleEvidence("AI Generated Essays Dataset.csv", 40, PositiveCounts(1, 1)),
    ),
    (
        "formulaic_filler",
        RuleEvidence("AI Generated Essays Dataset.csv", 40, PositiveCounts(1, 1)),
    ),
)
PHRASE_RULE_EVIDENCE = RULE_EVIDENCE
OMITTED_PHRASE_RULES = {
    "formulaic_closer_phrase": (
        "The document corpus truncates endings, so no held-out closer measurement exists."
    ),
}

def _weighted_pattern(marker: WeightedMarker) -> re.Pattern[str]:
    boundary = r"\b" + re.escape(marker.phrase) + r"\b"
    suffix = r"(?!\s+into\b)" if marker.phrase == "delve" else ""
    return re.compile(boundary + suffix, re.IGNORECASE)


_WEIGHTED_PATTERNS = tuple(
    (_weighted_pattern(marker), marker)
    for marker in WEIGHTED_MARKERS
)

def _visible_text(text: str) -> str:
    return "\n".join(
        _strip_inline_code(_strip_english_hidden(line))
        for _number, line in _markdown_prose_lines(text)
    )


def _non_overlapping_matches(matches: list[PhraseMatch]) -> tuple[PhraseMatch, ...]:
    accepted: list[PhraseMatch] = []
    for match in sorted(matches, key=lambda item: (item.start, -len(item.phrase))):
        match_end = match.start + len(match.phrase)
        if any(
            match.start < item.start + len(item.phrase) and item.start < match_end
            for item in accepted
        ):
            continue
        accepted.append(match)
    return tuple(accepted)


def _weighted_matches(text: str) -> tuple[PhraseMatch, ...]:
    matches = [
        PhraseMatch(match.group(), float(marker.weight), match.start())
        for pattern, marker in _WEIGHTED_PATTERNS
        for match in pattern.finditer(text)
    ]
    return _non_overlapping_matches(matches)


def _density(matches: tuple[PhraseMatch, ...], text: str) -> float:
    word_count = max(len(text.split()), 1)
    return sum(match.weight for match in matches) * 1000.0 / word_count


def _formulaic_scope(rule: str, text: str) -> str:
    if rule == "formulaic_opener":
        return text[:300]
    return text


def _sentence_context(text: str, found: re.Match[str]) -> tuple[str, str]:
    start = max(text.rfind(mark, 0, found.start()) for mark in (".", "!", "?", "\n")) + 1
    endings = [position for mark in (".", "!", "?", "\n") if (position := text.find(mark, found.end())) >= 0]
    end = min(endings, default=len(text))
    return text[start:found.start()], text[found.end():end]


def _meaningful_adverb(text: str, found: re.Match[str]) -> bool:
    before, after = _sentence_context(text, found)
    word = found.group().lower()
    if word == "literally":
        return _literal_use(before + after) and bool(re.search(r"\b(?:not|rather than|instead of)\b", after, re.I))
    if word in {"simply", "actually"}:
        return _literal_use(after if word == "simply" else before + after)
    if word in {"absolutely", "totally", "completely", "utterly", "entirely"}:
        return _literal_use(after) and len(after.split()) > 1
    return bool(word == "just" and re.search(r"\b(?:has|have|had)\s*$", before, re.I))


def _literal_jargon(text: str, found: re.Match[str]) -> bool:
    phrase = found.group().lower()
    if not (phrase.startswith("navigat") or "unpack" in phrase):
        return False
    return _literal_use(" ".join(text[found.end():].split()[:3]))


def _grounded_assertion(text: str, found: re.Match[str]) -> bool:
    _before, after = _sentence_context(text, found)
    reason = re.search(r"(?:\bbecause\b|:\s*)(.+)", after, re.I)
    if not reason:
        return False
    words = re.findall(r"\b[a-z]+\b", reason[1].lower())
    vague = {"it", "this", "that", "is", "are", "really", "very", "important", "hard", "matters"}
    return len(set(words) - vague) >= 4


def _temporal_day(text: str, found: re.Match[str]) -> bool:
    if found.group().lower() != "at the end of the day":
        return False
    _before, after = _sentence_context(text, found)
    return bool(re.search(
        r"\b(?:complete[ds]?|finished?|closed?|shut|ended?|depart(?:s|ed)?|arriv(?:es|ed)|"
        r"sunset|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", after, re.I,
    ))


def _literal_agency(text: str, found: re.Match[str]) -> bool:
    if not re.search(r"\b(?:demands?|shifts?|moves? toward)$", found.group(), re.I):
        return False
    _before, after = _sentence_context(text, found)
    return _literal_use(after)


def _ordinary_construction(_text: str, found: re.Match[str]) -> bool:
    return _literal_use(found.group())


def _additive_properties(text: str, found: re.Match[str]) -> bool:
    halves = re.fullmatch(r"not just (.+) but also", found.group(), re.I)
    if halves is None:
        return False
    _before, after = _sentence_context(text, found)
    return _literal_use(halves[1]) and _literal_use(after)


def _literal_office_idiom(text: str, found: re.Match[str]) -> bool:
    after = text[found.end():]
    return bool(found.group().lower().startswith("circl") and re.match(r"\s+to\b", after, re.I) and _literal_use(after))


def phrase_family_matches(patterns: tuple[re.Pattern[str], ...], text: str, literal: LiteralCheck | None = None) -> Iterator[re.Match[str]]:
    """Share contextual matching because phrase variants must keep the same meaning checks."""
    for pattern in patterns:
        if pattern.search(text) is None:
            continue
        for found in pattern.finditer(text):
            if literal is None or not literal(text, found):
                yield found


_FORMULAIC_RULES = {
    "formulaic_opener": PhraseFamily.compile(*FORMULAIC_OPENERS),
    "formulaic_filler": PhraseFamily.compile(*FILLER_PATTERNS),
    "filler_phrase": PhraseFamily.compile(*EXTRA_FILLER_PATTERNS),
    "throat_clearing_opener": PhraseFamily.compile(*THROAT_CLEARING_PATTERNS),
    "emphasis_crutch": PhraseFamily.compile(*EMPHASIS_CRUTCH_PATTERNS),
    "meta_commentary": PhraseFamily.compile(*META_COMMENTARY_PATTERNS),
    "telling_not_showing": PhraseFamily.compile(*TELLING_PATTERNS, literal=_grounded_assertion),
    "vague_declarative": PhraseFamily.compile(*VAGUE_DECLARATIVE_PATTERNS),
    "performative_emphasis": PhraseFamily.compile(*PERFORMATIVE_PATTERNS),
    "banned_adverb": PhraseFamily.compile(*BANNED_ADVERB_PATTERNS, literal=_meaningful_adverb),
    "business_jargon": PhraseFamily.compile(*JARGON_PATTERNS, literal=_literal_jargon),
}
_FORMULAIC_PATTERNS = {name: family.patterns for name, family in _FORMULAIC_RULES.items()}


def formulaic_filler_opener(text: str, found: re.Match[str]) -> bool:
    """Prefer the phrase row because matching openers repeat the same finding."""
    family = _FORMULAIC_RULES["formulaic_filler"]
    start = found.start() + len(found[0]) - len(found[0].lstrip())
    return any(
        match.start() == start
        for match in phrase_family_matches(family.patterns, text, family.literal)
    )


def _formulaic_matches(rule: str, text: str) -> tuple[PhraseMatch, ...]:
    family = _FORMULAIC_RULES[rule]
    matches = [
        PhraseMatch(text[match.start():match.end()], 0.0, match.start())
        for match in phrase_family_matches(family.patterns, _formulaic_scope(rule, text), family.literal)
    ]
    return _non_overlapping_matches(matches)


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _source_snippet(line: str, phrase: str) -> str:
    lowered = line.lower()
    phrase_start = lowered.find(phrase.lower())
    if phrase_start < 0:
        return line.strip()[:180]
    snippet_start = max(phrase_start - 70, 0)
    return line[snippet_start:snippet_start + 180].strip()


def _finding_detail(path: str, item: FindingMatch) -> str:
    if item.rule != "weighted_slop_marker":
        return f"Formulaic phrase {item.match.phrase!r} at offset {item.match.start} in {path}"
    assert item.density is not None
    return (
        f"Marker density is {item.density:.1f} per 1,000 words "
        f"(threshold {WEIGHTED_DENSITY_THRESHOLD:g}); {item.match.phrase!r} at offset {item.match.start} has weight {item.match.weight:g} in {path}"
    )


def _finding(context: ScanText, item: FindingMatch) -> FindingDict:
    line_number = _line_number(context.visible, item.match.start)
    source_lines = context.source.splitlines()
    source_line = source_lines[line_number - 1] if source_lines else ""
    finding = Finding(
        family="english",
        rule=item.rule,
        line=line_number,
        detail=_finding_detail(context.path, item),
        force=True,
        snippet=_source_snippet(source_line, item.match.phrase),
        action="Replace the phrase with a concrete statement.",
        path=None,
        severity=None,
        tool_use_id=None,
    )
    return cast(FindingDict, finding.to_dict())


def _weighted_findings(context: ScanText) -> list[FindingDict]:
    matches = _weighted_matches(context.visible)
    density = _density(matches, context.visible)
    if len(matches) < MINIMUM_WEIGHTED_MATCHES or density < WEIGHTED_DENSITY_THRESHOLD:
        return []
    return [
        _finding(context, FindingMatch("weighted_slop_marker", match, density))
        for match in matches
    ]


def _formulaic_findings(context: ScanText) -> Iterator[FindingDict]:
    visible = phrase_text(context.visible)
    for rule in _FORMULAIC_RULES:
        for match in _formulaic_matches(rule, visible):
            yield _finding(context, FindingMatch(rule, match, None))


def scan_slop_phrases(path: str, text: str, _config: Mapping[str, object]) -> list[FindingDict]:
    context = ScanText(path, text, _visible_text(text))
    findings = _weighted_findings(context)
    findings.extend(_formulaic_findings(context))
    return findings
