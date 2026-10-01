"""Stay STATIC, because each rule here reads German sentence shape from commas, verb positions, and punctuation."""
from __future__ import annotations

import re
from itertools import groupby

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import line_at, phrase_hits, sentence_hits, visible
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import line_at, phrase_hits, sentence_hits, visible
    from prose_language import ParagraphLanguage

NESTED_CLAUSES = Rule(
    "de_nested_clauses",
    Wording(
        "German nested clauses",
        "Flags a German sentence with more than three commas and two or more subordinate clauses inside it",
        "Split the sentence so each clause follows the last one.",
    ),
    Wording(
        "Schachtelsatz",
        "Meldet Sätze mit mehr als drei Kommas und mindestens zwei eingeschobenen Nebensätzen",
        "Teil den Satz, sodass die Nebensätze aufeinander folgen.",
    ),
)
VERB_BRACKET = Rule(
    "de_verb_bracket",
    Wording(
        "Wide German verb bracket",
        "Flags more than six words between a German modal or haben verb and the infinitive or participle it needs",
        "Move the closing verb forward, right after the core of the clause.",
    ),
    Wording(
        "Weite Verbklammer",
        "Meldet mehr als sechs Wörter zwischen Modalverb oder haben und dem Infinitiv oder Partizip",
        "Zieh den zweiten Verbteil nach vorn, direkt hinter den Kern des Satzes.",
    ),
)
UNEXPLAINED_ABBREVIATION = Rule(
    "de_unexplained_abbreviation",
    Wording(
        "German shortcut abbreviation",
        "Flags a German shortcut like usw., bzw., or d.h. that hides an unfinished thought",
        "Delete the abbreviation or write the sentence out.",
    ),
    Wording(
        "Unnötige Abkürzung",
        "Meldet Abkürzungen wie usw., bzw. oder d.h., hinter denen ein unfertiger Gedanke steckt",
        "Streich die Abkürzung oder schreib den Satz aus.",
    ),
)
EXCLAMATION_STACCATO = Rule(
    "de_exclamation_staccato",
    Wording(
        "German exclamation staccato",
        "Flags three or more short German sentences in a row that each end in an exclamation mark",
        "Join the fragments into one plain sentence that ends in a period.",
    ),
    Wording(
        "Ausrufezeichen-Stakkato",
        "Meldet drei oder mehr kurze Sätze hintereinander, die alle mit Ausrufezeichen enden",
        "Fass die Satzfetzen zu einem ruhigen Satz mit Punkt zusammen.",
    ),
)
CASUAL_GREETING = Rule(
    "de_casual_greeting",
    Wording(
        "Casual German greeting",
        "Flags a slangy German opener or sign-off like Tachchen or Und tschüss",
        "Delete the greeting and start with the point.",
    ),
    Wording(
        "Flapsige Anrede",
        "Meldet saloppe Anreden und Grußformeln wie Tachchen oder Und tschüss",
        "Streich den Gruß und fang mit der Sache an.",
    ),
)
INFORMATION_CLUSTER = Rule(
    "de_information_cluster",
    Wording(
        "German information cluster",
        "Flags a German sentence that packs more than eight list items and numbers into one span",
        "Split the items across two or more sentences.",
    ),
    Wording(
        "Informationscluster",
        "Meldet Sätze, die mehr als acht Aufzählungsglieder und Zahlen auf einmal liefern",
        "Verteil die Angaben auf zwei oder mehr Sätze.",
    ),
)

PREPOSITION = r"(?:mit|von|in|an|auf|für|bei|aus|zu|nach|über|unter|durch|gegen|ohne|um|vor|hinter)"
SUBORDINATOR = (
    r"(?:der|die|das|dem|den|dessen|deren|denen|welche[rmns]?|dass|weil|obwohl|während|nachdem"
    r"|wenn|falls|ob|da|bevor|seit|seitdem|sodass|damit|indem)"
)
COORDINATOR = r"(?:und|oder|aber|denn|doch|sondern)"
SUBORDINATE_OPENER_RE = re.compile(r"(?<=, )(?:" + PREPOSITION + r"\s+)?" + SUBORDINATOR + r"\b")
CLAUSE_COMMA_RE = re.compile(r",\s")
NESTED_MAX_COMMAS = 3
NESTED_MIN_OPENERS = 2

MODAL = (
    r"(?:kann|kannst|können|könnt|konnte|konnten|könnte|könnten|muss|musst|müssen|müsst|musste|mussten"
    r"|müsste|müssten|darf|darfst|dürfen|dürft|durfte|durften|dürfte|dürften|will|willst|wollen|wollt"
    r"|wollte|wollten|soll|sollst|sollen|sollt|sollte|sollten|möchte|möchtest|möchten|möchtet)"
)
HABEN = r"(?:habe|hast|hat|haben|habt|hatte|hattest|hatten|hattet)"
INFINITIVE = r"(?:[a-zäöüß]\w*(?:en|rn|ln)|sein|tun)"
PARTICIPLE = r"(?:ge[a-zäöüß]+(?:t|en))"
CLAUSE_END = r"(?=\s*(?:[,;:.!?]|$))"
BRACKET_RES = tuple(
    re.compile(r"\b" + opener + r"\b(?!\s*[,;:.!?])(?P<gap>(?:\W+\w+)*?)\W+" + closer + r"\b" + CLAUSE_END)
    for opener, closer in ((MODAL, INFINITIVE), (HABEN, PARTICIPLE))
)
NEW_MAIN_CLAUSE_RE = re.compile(r"[;:]|,\s+" + COORDINATOR + r"\b")
BRACKET_MAX_GAP = 6

ABBREVIATION_RE = re.compile(
    r"(?<!\w)(?:usw\.|bzw\.|[dD]\.\s?h\.|u\.\s?U\.|dergl\.|s\.\s?o\.|Fam\.|Fa\.|MfG\b\.?|wg\.)"
)

STACCATO_SENTENCE_RE = re.compile(r"[^.!?\s][^.!?]*[.!?]+")
STACCATO_MAX_WORDS = 5
STACCATO_MIN_RUN = 3

CASUAL_GREETING_RE = re.compile(
    r"\A\s*(?:Hi|Tachchen|Moin\s+Moin|Halli-Hallo)\b"
    r"|(?:Tschüssi|Mach['’]s\s+gut,?\s+Alter|Und\s+[Tt]schüss|So\s+long)[\s!.]*\Z"
)

LIST_COMMA_RE = re.compile(r",(?=\s)(?!\s+(?:" + PREPOSITION + r"\s+)?(?:" + SUBORDINATOR + "|" + COORDINATOR + r")\b)")
NUMBER_RE = re.compile(r"\d+(?:[.,:/-]\d+)*")
WHOLE_SENTENCE_RE = re.compile(r"\S(?:.*\S)?", re.DOTALL)
CLUSTER_MAX_ITEMS = 8


def _nested_clauses(sentence: str) -> re.Match[str] | None:
    """Require both signals, because a plain list has many commas and no subordinate clause."""
    openers = list(SUBORDINATE_OPENER_RE.finditer(sentence))
    commas = len(CLAUSE_COMMA_RE.findall(sentence))
    if commas > NESTED_MAX_COMMAS and len(openers) >= NESTED_MIN_OPENERS:
        return openers[0]
    return None


def _too_wide(found: re.Match[str]) -> bool:
    """Stop at a coordinated main clause, because its verb closes a new bracket, not the old one."""
    gap = found.group("gap")
    return NEW_MAIN_CLAUSE_RE.search(gap) is None and len(re.findall(r"\w+", gap)) > BRACKET_MAX_GAP


def _wide_bracket(sentence: str) -> re.Match[str] | None:
    found = (match for bracket in BRACKET_RES for match in bracket.finditer(sentence))
    return next((match for match in found if _too_wide(match)), None)


def _information_cluster(sentence: str) -> re.Match[str] | None:
    """Count list commas and numbers only, because German capitalizes every noun and hides proper names."""
    items = len(LIST_COMMA_RE.findall(sentence)) + len(NUMBER_RE.findall(sentence))
    return WHOLE_SENTENCE_RE.search(sentence) if items > CLUSTER_MAX_ITEMS else None


def _is_staccato(sentence: str) -> bool:
    return sentence.rstrip().endswith("!") and len(re.findall(r"\w+", sentence)) <= STACCATO_MAX_WORDS


def _run_hit(paragraph: ParagraphLanguage, run: list[re.Match[str]]) -> Hit:
    snippet = " ".join(found.group(0).strip() for found in run)
    return Hit(EXCLAMATION_STACCATO.name, line_at(paragraph, run[0].start()), snippet, run[0].group(0).strip())


def _staccato_runs(paragraph: ParagraphLanguage) -> list[Hit]:
    sentences = STACCATO_SENTENCE_RE.finditer(visible(paragraph.text))
    grouped = groupby(sentences, key=lambda found: _is_staccato(found.group(0)))
    runs = [list(group) for staccato, group in grouped if staccato]
    return [_run_hit(paragraph, run) for run in runs if len(run) >= STACCATO_MIN_RUN]


def _check(path: str, paragraphs: list[ParagraphLanguage]) -> list[Hit]:
    return [
        *sentence_hits(NESTED_CLAUSES.name, paragraphs, _nested_clauses),
        *sentence_hits(VERB_BRACKET.name, paragraphs, _wide_bracket),
        *phrase_hits(UNEXPLAINED_ABBREVIATION.name, paragraphs, ABBREVIATION_RE),
        *(hit for paragraph in paragraphs for hit in _staccato_runs(paragraph)),
        *phrase_hits(CASUAL_GREETING.name, paragraphs, CASUAL_GREETING_RE),
        *sentence_hits(INFORMATION_CLUSTER.name, paragraphs, _information_cluster),
    ]


RULE_SET = RuleSet(
    rules=(
        NESTED_CLAUSES, VERB_BRACKET, UNEXPLAINED_ABBREVIATION,
        EXCLAMATION_STACCATO, CASUAL_GREETING, INFORMATION_CLUSTER,
    ),
    check=_check,
)
