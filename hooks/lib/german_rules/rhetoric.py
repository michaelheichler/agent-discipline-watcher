# SPDX-FileCopyrightText: Martin Moeller, humanizer-de trigger lists (see NOTICE)
# SPDX-License-Identifier: MIT AND CC-BY-SA-4.0
"""Stay STATIC, because each rule here matches a humanizer-de rhetoric pattern by its own trigger words (decision Q13)."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import phrase_hits
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import phrase_hits
    from prose_language import ParagraphLanguage

TRIAD = Rule(
    "de_triad",
    Wording(
        "German triad",
        "Flags a German list of exactly three lowercase words, like vielfältig, kreativ und stark, that closes a clause",
        "Keep the two items that carry the point.",
    ),
    Wording(
        "Trikolon",
        "Meldet Dreierreihen aus kleingeschriebenen Wörtern wie vielfältig, kreativ und stark am Satzende",
        "Behalte die zwei Glieder, die die Aussage tragen.",
    ),
    state="off",
)
AUTHORITY_PHRASE = Rule(
    "de_authority_phrase",
    Wording(
        "German authority phrase",
        "Flags a German lead-in like Die eigentliche Frage ist or Im Kern that dresses a plain claim as insight",
        "Delete the lead-in and state the claim.",
    ),
    Wording(
        "Autoritäts-Floskel",
        "Meldet Einleitungen wie Die eigentliche Frage ist oder Im Kern, die eine schlichte Aussage als Einsicht verkaufen",
        "Streich die Einleitung und sag die Aussage.",
    ),
    state="off",
)
SIGNPOSTING = Rule(
    "de_signposting",
    Wording(
        "German signposting",
        "Flags a German announcement like Schauen wir uns an or Kommen wir zu that promises content instead of giving it",
        "Delete the announcement and give the content.",
    ),
    Wording(
        "Ankündigung statt Inhalt",
        "Meldet Ankündigungen wie Schauen wir uns an oder Kommen wir zu, die Inhalt versprechen statt ihn zu liefern",
        "Streich die Ankündigung und liefer den Inhalt.",
    ),
)
APHORISM_FORMULA = Rule(
    "de_aphorism_formula",
    Wording(
        "German aphorism formula",
        "Flags a German fill-in aphorism like X ist die Sprache des Y or X wird zur Falle",
        "Replace the formula with the concrete claim it hints at.",
    ),
    Wording(
        "Aphorismus-Formel",
        "Meldet Schablonen wie X ist die Sprache des Y oder X wird zur Falle",
        "Ersetz die Formel durch die konkrete Aussage dahinter.",
    ),
    state="off",
)
ANNOUNCING_CLEFT = Rule(
    "de_announcing_cleft",
    Wording(
        "German announcing cleft",
        "Flags two or more German cleft sentences like Was mich überrascht hat, war that announce a point before making it",
        "State the point directly, such as Die Ladezeit hat mich überrascht.",
    ),
    Wording(
        "Ankündigungs-Spaltsatz",
        "Meldet zwei oder mehr Spaltsätze wie Was mich überrascht hat, war, die eine Aussage erst ankündigen",
        "Sag die Aussage direkt, etwa Die Ladezeit hat mich überrascht.",
    ),
    state="off",
)

# humanizer-de Muster 9 shape, because Q13 credits it.
TRIAD_ITEM = r"[a-zäöüß]{4,}"
TRIAD_RE = re.compile(
    r"(?<!,\s)\b" + TRIAD_ITEM + r",\s+" + TRIAD_ITEM + r"\s+(?:und|oder)\s+" + TRIAD_ITEM
    + r"\b(?=\s*(?:[.!?;:,)]|$))"
)
# humanizer-de Muster 32 phrases, because Q13 credits it.
AUTHORITY_RE = re.compile(
    r"\b(?:[Dd]ie\s+eigentliche\s+Frage\s+ist|Im\s+Kern\b(?!\s+(?:des|der|eines|einer|von)\b)"
    r"|[Ii]n\s+Wirklichkeit|[Ww]as\s+wirklich\s+zählt|[Ii]m\s+Grunde\s+genommen|[Dd]as\s+tiefere\s+Problem"
    r"|[Ww]orauf\s+es\s+wirklich\s+ankommt|[Dd]er\s+Kern\s+der\s+Sache|[Ll]etztlich\s+geht\s+es\s+um"
    r"|So\s+betrachtet|So\s+gelesen|Anders\s+gerahmt)\b"
)
# humanizer-de Muster 33 phrases, because Q13 credits it.
SIGNPOSTING_RE = re.compile(
    r"\b(?:Schauen\s+wir\s+uns\b|Lass(?:en\s+Sie|t)?\s+uns\b[^.!?]*?\berkunden"
    r"|Hier\s+ist,\s+was\s+(?:Sie|du|ihr)\s+wissen\s+(?:müssen|musst|müsst)|Die\s+Sache\s+ist\s+die"
    r"|Ohne\s+weitere\s+Umschweife|[Ww]erfen\s+wir\s+(?:jetzt\s+)?einen\s+Blick|Kommen\s+wir\s+zu[mr]?\b"
    r"|Tauchen\s+wir\b|(?:Was\s+als\s+Nächstes\s+passiert|Warum\s+das\s+wichtig\s+ist|Das\s+große\s+Bild)\s*:)"
)
# humanizer-de Muster 56 templates, because Q13 credits it.
APHORISM_RE = re.compile(
    r"\bist\s+die\s+(?:Sprache|Währung|Architektur)\s+(?:des|der)\b|\bwird\s+zur\s+Falle\b"
    r"|\bist\s+kein\s+Werkzeug,\s+sondern\s+ein\s+Spiegel\b|\b[Ii]m\s+Kern\s+von\s+[^.!?]{1,60}?\s+steht\b"
)
# humanizer-de Muster 67 shapes, because Q13 credits it.
CLEFT_RE = re.compile(
    r"\bWas\s+[^,.!?:]{1,60}?,\s+(?:war|ist|waren|sind)\b|\bWas\s+[^,.!?:]{1,40}?:"
    r"|\bDer\s+Punkt,\s+der\s+[^,.!?]{1,60}?,\s+(?:war|ist)\b"
)
CLEFT_MIN_COUNT = 2


def _repeated(hits: list[Hit], minimum: int) -> list[Hit]:
    """Report only a pile-up, because humanizer-de calls one cleft sentence harmless and the repetition the tell."""
    return hits if len(hits) >= minimum else []


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *phrase_hits(TRIAD.name, paragraphs, TRIAD_RE),
        *phrase_hits(AUTHORITY_PHRASE.name, paragraphs, AUTHORITY_RE),
        *phrase_hits(SIGNPOSTING.name, paragraphs, SIGNPOSTING_RE),
        *phrase_hits(APHORISM_FORMULA.name, paragraphs, APHORISM_RE),
        *_repeated(phrase_hits(ANNOUNCING_CLEFT.name, paragraphs, CLEFT_RE), CLEFT_MIN_COUNT),
    ]


RULE_SET = RuleSet(
    rules=(TRIAD, AUTHORITY_PHRASE, SIGNPOSTING, APHORISM_FORMULA, ANNOUNCING_CLEFT),
    check=_check,
)
