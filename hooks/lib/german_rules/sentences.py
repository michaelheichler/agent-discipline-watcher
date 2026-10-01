"""Stay STATIC, because each rule here judges one German sentence by its word pattern, not by a parse."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import sentence_hits
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import sentence_hits
    from prose_language import ParagraphLanguage

NOUN_STYLE = Rule(
    "de_noun_style",
    Wording(
        "German noun style",
        "Flags a German -ung, -heit, -keit, or -schaft noun propped up by a weak verb like erfolgt",
        "Turn the noun back into a verb, such as versenden for der Versand erfolgt.",
    ),
    Wording(
        "Nominalstil",
        "Meldet Substantive auf -ung, -heit, -keit oder -schaft mit Stützverb wie erfolgt oder findet statt",
        "Mach aus dem Substantiv wieder ein Verb, etwa versenden statt der Versand erfolgt.",
    ),
)
MODAL_VERB = Rule(
    "de_modal_verb",
    Wording(
        "German modal verb padding",
        "Flags a German modal verb like möchten or könnte that pushes the real verb to the end",
        "Say what happens with the main verb.",
    ),
    Wording(
        "Modalverb schiebt das Verb ans Ende",
        "Meldet Modalverben wie möchten oder könnte, die das Vollverb ans Satzende schieben",
        "Sag mit dem Vollverb, was passiert.",
    ),
)
DOUBLE_NEGATION = Rule(
    "de_double_negation",
    Wording(
        "German double negation",
        "Flags a German sentence with two or more negations like nicht, kein, or an un- word",
        "Say it as one positive statement.",
    ),
    Wording(
        "Doppelte Verneinung",
        "Meldet Sätze mit zwei oder mehr Verneinungen wie nicht, kein oder einem Wort mit un-",
        "Formulier den Satz positiv.",
    ),
)
STACKED_CONDITIONS = Rule(
    "de_stacked_conditions",
    Wording(
        "Stacked German conditions",
        "Flags a German sentence that stacks two or more wenn, falls, or sofern clauses",
        "State the result and keep at most one condition.",
    ),
    Wording(
        "Gestapelte Bedingungen",
        "Meldet Sätze, die zwei oder mehr Bedingungen mit wenn, falls oder sofern stapeln",
        "Sag das Ergebnis und behalte höchstens eine Bedingung.",
    ),
)

NOMINALIZATION_RE = re.compile(r"\b[A-ZÄÖÜ][a-zäöüß]+(?:ung|heit|keit|schaft)(?:en)?\b")
CARRIER_VERB_RE = re.compile(
    r"\berfolg(?:t|te|ten|en)\b|\b(?:geschieht|geschah|geschahen|geschehen)\b"
    r"|\bpassier(?:t|te|ten|en)\b|\bereignet(?:e|en)?\b|\bstattfind\w*|\bstattgefunden\b"
    r"|\b(?:findet|finden|fand|fanden)\b[^,;:]*?\bstatt\b"
    r"|\bvorlieg\w*|\bvorgelegen\b|\b(?:liegt|liegen|lag|lagen)\b[^,;:]*?\bvor\b"
)
MODAL = (
    r"(?:kann|kannst|können|könnt|konnte|konnten|könnte|könnten|muss|musst|müssen|müsst|musste|mussten"
    r"|müsste|müssten|möchte|möchtest|möchten|möchtet|darf|darfst|dürfen|dürft|durfte|durften|dürfte"
    r"|dürften|will|willst|wollen|wollt|wollte|wollten|soll|sollst|sollen|sollt|sollte|sollten"
    r"|würde|würdest|würden|würdet)"
)
CLAUSE_END = r"(?=\s*(?:[,;:.!]|$))"
INFINITIVE = r"[a-zäöüß]\w*en"
MODAL_RE = re.compile(
    r"\b" + MODAL + r"\b[^,;:.!?]*?\b" + INFINITIVE + r"\b" + CLAUSE_END
    + r"|\b" + INFINITIVE + r"\s+" + MODAL + r"\b" + CLAUSE_END
)
NEGATION = r"\b(?:nicht|kein(?:e[nmrs]?)?|nie|niemals|[Uu]n(?!ser|ter|ten|i|gefähr|bedingt)[a-zäöüß]{3,})\b"
DOUBLE_NEGATION_RE = re.compile(NEGATION + r".*?" + NEGATION, re.DOTALL)
CONDITION = r"\b(?:[Ww]enn|[Ff]alls|[Ss]ofern)\b"
STACKED_CONDITIONS_RE = re.compile(CONDITION + r".*?" + CONDITION, re.DOTALL)


def _noun_style(sentence: str) -> re.Match[str] | None:
    """Gate on the noun first, because a carrier verb alone often names a real event."""
    if NOMINALIZATION_RE.search(sentence) is None:
        return None
    return CARRIER_VERB_RE.search(sentence)


def _modal_padding(sentence: str) -> re.Match[str] | None:
    """Skip questions, because a polite request like Darf ich bitten is the exception Gottschling names."""
    if sentence.rstrip().endswith("?"):
        return None
    return MODAL_RE.search(sentence)


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *sentence_hits(NOUN_STYLE.name, paragraphs, _noun_style),
        *sentence_hits(MODAL_VERB.name, paragraphs, _modal_padding),
        *sentence_hits(DOUBLE_NEGATION.name, paragraphs, DOUBLE_NEGATION_RE.search),
        *sentence_hits(STACKED_CONDITIONS.name, paragraphs, STACKED_CONDITIONS_RE.search),
    ]


RULE_SET = RuleSet(
    rules=(NOUN_STYLE, MODAL_VERB, DOUBLE_NEGATION, STACKED_CONDITIONS),
    check=_check,
)
