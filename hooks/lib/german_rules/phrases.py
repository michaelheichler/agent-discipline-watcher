"""Stay STATIC, because each rule here matches a stock phrase from humanizer-de references/patterns.md (decision Q13)."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import SentenceFinder, line_at, phrase_hits, sentence_hits, sentence_spans, visible
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import SentenceFinder, line_at, phrase_hits, sentence_hits, sentence_spans, visible
    from prose_language import ParagraphLanguage

SYMBOLISM = Rule(
    "de_symbolism_inflation",
    Wording(
        "German symbolism inflation",
        "Flags a German phrase like steht als Zeugnis für or spielt eine wichtige Rolle that inflates a plain fact",
        "State the plain fact the phrase points at.",
    ),
    Wording(
        "Übertriebene Symbolik",
        "Meldet Wendungen wie „steht als Zeugnis für“ oder „spielt eine wichtige Rolle“, die eine schlichte Tatsache aufblähen",
        "Nenn die Tatsache direkt.",
    ),
    state="off",
)
META_COMMENTARY = Rule(
    "de_meta_commentary",
    Wording(
        "German meta commentary",
        "Flags a German phrase like es ist wichtig zu bemerken that talks about the text instead of saying the point",
        "Delete the phrase and state the point.",
    ),
    Wording(
        "Meta-Kommentar",
        "Meldet Wendungen wie „es ist wichtig zu bemerken“, die über den Text reden statt die Sache zu sagen",
        "Streich die Wendung und sag die Sache.",
    ),
    state="enforce",
)
SECTION_SUMMARY = Rule(
    "de_section_summary",
    Wording(
        "German section summary opener",
        "Flags a German sentence that opens with zusammenfassend, insgesamt, or kurz gesagt to repeat what came before",
        "Delete the summary sentence or fold its one new fact into the text.",
    ),
    Wording(
        "Abschnitts-Zusammenfassung",
        "Meldet Sätze, die mit „zusammenfassend“, „insgesamt“ oder „kurz gesagt“ beginnen und Gesagtes wiederholen",
        "Streich den Satz oder bau seine neue Tatsache in den Text ein.",
    ),
    state="off",
)
AI_MARKER_VOCABULARY = Rule(
    "de_ai_marker_vocabulary",
    Wording(
        "German AI marker vocabulary",
        "Flags three or more German AI marker words like beleuchten, nahtlos, or spannend in one text",
        "Use the ordinary word, such as untersuchen for beleuchten.",
    ),
    Wording(
        "KI-Marker-Vokabular",
        "Meldet drei oder mehr KI-Marker wie „beleuchten“, „nahtlos“ oder „spannend“ in einem Text",
        "Nimm das gewöhnliche Wort, etwa „untersuchen“ statt „beleuchten“.",
    ),
    state="off",
)
CORPORATE_CLOSING = Rule(
    "de_corporate_closing",
    Wording(
        "German aspirational closing line",
        "Flags a German paragraph that ends on a phrase like bestens aufgestellt or auf Erfolgskurs",
        "End on the last concrete fact instead.",
    ),
    Wording(
        "Aspirativer Unternehmensschluss",
        "Meldet Absätze, die mit Wendungen wie „bestens aufgestellt“ oder „auf Erfolgskurs“ enden",
        "Hör mit der letzten konkreten Tatsache auf.",
    ),
)

# humanizer-de Muster 1. No steht für, because docs use it.
SYMBOLISM_RE = re.compile(
    r"(?i:\b(?:steh\w*|stand|standen)\s+als\s+Zeugnis\s+für\b"
    r"|\b(?:ist|sind|war|waren)\s+ein\s+Beweis\s+für\b"
    r"|\bspiel\w*\s+eine\s+wichtige\s+Rolle\b|\bsymbolisier\w*)"
)
# humanizer-de Muster 3, because Q13 credits it.
META_COMMENTARY_RE = re.compile(
    r"(?i:\bes\s+ist\s+wichtig\s+zu\s+(?:bemerken|beachten)\b|\bes\s+kann\s+nicht\s+ignoriert\s+werden\b"
    r"|\bkeine\s+Diskussion\s+wäre\s+vollständig\s+ohne\b|\bes\s+sollte\s+hervorgehoben\s+werden\b"
    r"|\bes\s+ist\s+erwähnenswert\b|\bzu\s+beachten\s+ist,?\s+dass\b)"
)
# humanizer-de Muster 5, narrow because totals are facts.
SECTION_SUMMARY_RE = re.compile(
    r"Zusammenfassend\b|Kurz\s+gesagt\b|Im\s+Wesentlichen\b"
    r"|Abschließend\b(?=\s*[,:]|\s+(?:lässt\s+sich|kann\s+man|bleibt|ist\s+festzuhalten|sei|zeigt\s+sich)\b)"
    r"|Insgesamt\b(?![\s\S]*\d)"
)
LEADING_SPACE_RE = re.compile(r"\s*")
# humanizer-de Muster 64 AI_MARKERS, because Q13.
AI_MARKER_RE = re.compile(
    r"(?i:\bbeleucht(?!ung|er)\w*|\beintauch(?!ung)\w*|\bunterstreich(?!ung)\w*|\baufzeig(?!ung)\w*"
    r"|\bspannend\w*|\bentscheidend\w*|\bma(?:ß|ss)geblich\w*|\bnahtlos\w*|\bvielschichtig\w*"
    r"|\bfacettenreich\w*|\bdynamisch\w*|\bganzheitlich\w*|\bma(?:ß|ss)geschneidert\w*"
    r"|\bdigitale\w*\s+landschaft\w*|\bzusammenspiel\w*)"
)
AI_MARKER_MIN_COUNT = 3
# humanizer-de Muster 38, because Q13 credits it.
CORPORATE_CLOSING_RE = re.compile(
    r"(?i:\bbestens\s+aufgestellt\b|\bdie\s+Möglichkeiten\s+sind\s+grenzenlos\b"
    r"|\bbereit\s+für\s+die\s+nächste\s+Stufe\b|\ban\s+der\s+Schwelle\s+zu\s+einer\s+neuen\s+Ära\b"
    r"|\bdie\s+Weichen\s+sind\s+gestellt\b|\bmit\s+Zuversicht\s+in\s+die\s+Zukunft\b"
    r"|\bdas\s+Potenzial\s+ist\s+enorm\b|\bauf\s+Erfolgskurs\b)"
)


def opening(pattern: re.Pattern[str]) -> SentenceFinder:
    """Match only at a sentence start, because these stock phrases are tells as openers and plain words elsewhere."""
    def finder(sentence: str) -> re.Match[str] | None:
        return pattern.match(sentence, LEADING_SPACE_RE.match(sentence).end())
    return finder


def _counted(hits: list[Hit], minimum: int) -> list[Hit]:
    """Report every place once the count clears, because humanizer-de counts markers per text."""
    return hits if len(hits) >= minimum else []


def _closing_hits(rule: str, paragraphs: list[ParagraphLanguage], pattern: re.Pattern[str]) -> list[Hit]:
    """Read only the last sentence, because the catalog flags these phrases as a closing line."""
    hits = []
    for paragraph in paragraphs:
        spans = sentence_spans(visible(paragraph.text))
        offset, sentence = spans[-1] if spans else (0, "")
        found = pattern.search(sentence)
        if found is not None:
            hits.append(Hit(rule, line_at(paragraph, offset + found.start()), sentence, found.group(0)))
    return hits


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *phrase_hits(SYMBOLISM.name, paragraphs, SYMBOLISM_RE),
        *phrase_hits(META_COMMENTARY.name, paragraphs, META_COMMENTARY_RE),
        *sentence_hits(SECTION_SUMMARY.name, paragraphs, opening(SECTION_SUMMARY_RE)),
        *_counted(phrase_hits(AI_MARKER_VOCABULARY.name, paragraphs, AI_MARKER_RE), AI_MARKER_MIN_COUNT),
        *_closing_hits(CORPORATE_CLOSING.name, paragraphs, CORPORATE_CLOSING_RE),
    ]


RULE_SET = RuleSet(
    rules=(SYMBOLISM, META_COMMENTARY, SECTION_SUMMARY, AI_MARKER_VOCABULARY, CORPORATE_CLOSING),
    check=_check,
)
