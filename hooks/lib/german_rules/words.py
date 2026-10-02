# SPDX-FileCopyrightText: Martin Moeller, humanizer-de trigger lists (see NOTICE)
# SPDX-License-Identifier: MIT AND CC-BY-SA-4.0
"""Stay STATIC, because each rule here matches a fixed German word or phrase list from the style catalog."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import phrase_hits, sentence_hits
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import phrase_hits, sentence_hits
    from prose_language import ParagraphLanguage

FILLER_WORD = Rule(
    "de_filler_word",
    Wording(
        "German filler word",
        "Flags a German particle like eigentlich or irgendwie that adds no meaning",
        "Delete the filler word.",
    ),
    Wording(
        "Füllwort",
        "Meldet Füllwörter wie eigentlich oder irgendwie, die nichts aussagen",
        "Streich das Füllwort.",
    ),
    state="off",
)
EMPTY_INTENSIFIER = Rule(
    "de_empty_intensifier",
    Wording(
        "German empty intensifier",
        "Flags a German booster like sehr, absolut, or völlig that inflates a claim without proof",
        "Delete the booster or back the claim with a fact.",
    ),
    Wording(
        "Blähwort",
        "Meldet Verstärker wie sehr, absolut oder völlig, die eine Aussage ohne Beleg aufblähen",
        "Streich das Blähwort oder belege die Aussage.",
    ),
    state="off",
)
REDUNDANT_PAIR = Rule(
    "de_redundant_pair",
    Wording(
        "German redundant pair",
        "Flags a German phrase that says one thing twice, like weißer Schimmel or nie und nimmer",
        "Keep one of the two words.",
    ),
    Wording(
        "Tautologie oder Pleonasmus",
        "Meldet Wendungen, die dasselbe zweimal sagen, etwa weißer Schimmel oder nie und nimmer",
        "Behalte nur eines der beiden Wörter.",
    ),
)
STRETCHED_VERB = Rule(
    "de_stretched_verb",
    Wording(
        "German stretched verb",
        "Flags a phrase like in Frage stellen, or stacked stand-ins like fungiert als, where one plain verb works",
        "Use the plain verb, such as bezweifeln, ist, or hat.",
    ),
    Wording(
        "Streckverb",
        "Meldet Fügungen wie in Frage stellen und gehäufte Ersatzverben wie fungiert als",
        "Nimm das einfache Verb, etwa bezweifeln, ist oder hat.",
    ),
)
ANGLICISM = Rule(
    "de_anglicism",
    Wording(
        "German anglicism calque",
        "Flags a word-for-word English transfer like am Ende des Tages or Potenzial freischalten",
        "Use the German phrase, such as schließlich for am Ende des Tages.",
    ),
    Wording(
        "Anglizismus-Struktur",
        "Meldet wörtlich übertragene englische Wendungen wie am Ende des Tages oder Potenzial freischalten",
        "Nimm die deutsche Wendung, etwa schließlich statt am Ende des Tages.",
    ),
    state="off",
)
ABSTRACT_NOUNS = Rule(
    "de_abstract_nouns",
    Wording(
        "Stacked German abstract nouns",
        "Flags three or more umbrella nouns like Maßnahmen or Lösungen standing in for named things",
        "Name the concrete thing instead of the umbrella noun.",
    ),
    Wording(
        "Gestapelte Oberbegriffe",
        "Meldet drei oder mehr Oberbegriffe wie Maßnahmen oder Lösungen statt der konkreten Sache",
        "Nenn die konkrete Sache statt des Oberbegriffs.",
    ),
    state="off",
)

FILLER_PARTICLES = r"(?i:\b(?:irgendwie|eigentlich|jedoch|obschon|na|nunmehr|lediglich)\b)"
PARTICLE_DENN_NOT_CONJUNCTION = r"(?<!,)(?<!,\s)\bdenn\b"
FILLER_RE = re.compile(FILLER_PARTICLES + "|" + PARTICLE_DENN_NOT_CONJUNCTION)
INTENSIFIER_RE = re.compile(
    r"(?i:\b(?:(?<!voll und )ganz|sehr|durchaus|unbedingt|absolut|völlig|total"
    r"|anmiet\w*|angemietet\w*|unkosten)\b)"
)
REDUNDANT_RE = re.compile(
    r"(?i:\bnie\s+und\s+nimmer\b|\bimmer\s+und\s+ewig\b|\bweiße[nrms]?\s+Schimmel\w*"
    r"|\bgemachten?\s+Erfahrung(?:en)?\b|\btelefonische[nrms]?\s+Anruf\w*|\bvoll\s+und\s+ganz\b)"
)
_BRING = r"bring\w*|brachte\w*|gebracht|komm\w*|kam\w*|gekommen"
_NEHMEN = r"nehm\w*|nimm\w*|nahm\w*|genommen"
STRETCHED_PAIRS = tuple(
    (re.compile(noun), re.compile(r"\b(?:" + verb + r")\b"))
    for noun, verb in (
        (r"\b(?:[Ii]n\s+Frage|[Ii]nfrage)\b", r"stell\w*|gestellt"),
        (r"\b[Zz]ur\s+Sprache\b", _BRING),
        (r"\b[Zz]ur\s+Anwendung\b", _BRING),
        (r"\b[Ii]n\s+Erwägung\b", r"zieh\w*|zog\w*|gezogen"),
        (r"\b[Zz]ur\s+Kenntnis\b", _BRING + "|" + _NEHMEN),
        (r"\b[Ii]n\s+Gang\b", r"setz\w*|gesetzt|" + _BRING),
        (r"\bRache\b", _NEHMEN),
    )
)
# humanizer-de Muster 65 words, because Q13 credits it.
COPULA_RE = re.compile(
    r"(?i:\bfungiert\s+als\w*|\bdient\s+als\w*|\bverfügt\s+über\w*|\bverfuegt\s+ueber\w*"
    r"|\bzeichnet\s+sich\w*|\berweist\s+sich\s+als\w*|\brepräsentiert\w*|\brepraesentiert\w*)"
)
COPULA_MIN_COUNT = 2
# humanizer-de Muster 45 calques, because Q21 follows it.
ANGLICISM_RE = re.compile(
    r"(?i:\bam\s+Ende\s+des\s+Tages\b|\bin\s+Reihenfolge\s+zu\b|\bzu\s+Beginn\s+mit\b"
    r"|\bmacht\s+keinen\s+Unterschied\s+für\s+mich\b|\bVeränderung(?:en)?\s+um(?:zu)?arm\w*"
    r"|\bPoten[tz]iale?\s+frei(?:zu)?schalt\w*|\bdie\s+Reibung\s+fällt\b|\bsimpler\s+gegangen\b"
    r"|\bgegen\s+echten\s+Output\s+iterier\w*|\bder\s+Filter\s+bei\s+der\s+Arbeit\b)"
)
# humanizer-de Muster 58 words, because Q13 credits it.
ABSTRACT_RE = re.compile(
    r"(?i:\bmaßnahm\w*|\bmassnahm\w*|\baspekt(?:e|en|es)?\b|\blösung\w*|\bloesung\w*"
    r"|\bherausforderung\w*|\bfaktor\w*|\bprozess(?:e|en|es)?\b)"
)
ABSTRACT_MIN_COUNT = 3


def _stretched_phrase(sentence: str) -> re.Match[str] | None:
    for noun, verb in STRETCHED_PAIRS:
        found = noun.search(sentence)
        if found is not None and verb.search(sentence):
            return found
    return None


def _counted(hits: list[Hit], minimum: int) -> list[Hit]:
    """Report every place once the count clears, because humanizer-de counts per text, not per sentence."""
    return hits if len(hits) >= minimum else []


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *phrase_hits(FILLER_WORD.name, paragraphs, FILLER_RE),
        *phrase_hits(EMPTY_INTENSIFIER.name, paragraphs, INTENSIFIER_RE),
        *phrase_hits(REDUNDANT_PAIR.name, paragraphs, REDUNDANT_RE),
        *sentence_hits(STRETCHED_VERB.name, paragraphs, _stretched_phrase),
        *_counted(phrase_hits(STRETCHED_VERB.name, paragraphs, COPULA_RE), COPULA_MIN_COUNT),
        *phrase_hits(ANGLICISM.name, paragraphs, ANGLICISM_RE),
        *_counted(phrase_hits(ABSTRACT_NOUNS.name, paragraphs, ABSTRACT_RE), ABSTRACT_MIN_COUNT),
    ]


RULE_SET = RuleSet(
    rules=(FILLER_WORD, EMPTY_INTENSIFIER, REDUNDANT_PAIR, STRETCHED_VERB, ANGLICISM, ABSTRACT_NOUNS),
    check=_check,
)
