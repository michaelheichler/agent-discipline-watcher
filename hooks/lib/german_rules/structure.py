"""Stay STATIC, because each rule here reads German sentence shape from commas, verb positions, and punctuation."""
from __future__ import annotations

import re
from itertools import groupby

try:
    from . import Hit, Rule, RuleSet, Wording
    from ._text import phrase_hits, placed, sentence_hits, text_units
    from ..german_verbs import is_finite, is_infinitive
    from ..prose_language import ParagraphLanguage
except ImportError:
    from german_rules import Hit, Rule, RuleSet, Wording
    from german_rules._text import phrase_hits, placed, sentence_hits, text_units
    from german_verbs import is_finite, is_infinitive
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
    state="off",
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
    state="off",
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
    state="off",
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
    state="off",
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
    state="off",
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
LIST_CLOSE_RE = re.compile(r"(\S)\s+(?:und|oder)\s+(\S)")
CLOSE_RIGHT_RE = re.compile(r"[^,]*?(?=,|\s+" + COORDINATOR + r"\b|$)")
DETERMINER = r"(?:der|die|das|dem|den|des|eine?[mnrs]?|keine?[mnrs]?|(?:mein|dein|sein|ihr|unser|euer|eur)(?:e[mnrs]?)?|diese?[mnrs]?|jede[mnrs]?|alle)"
NOT_VERB_SLOT_RE = re.compile(r"(?:" + PREPOSITION + r"|am|im|vom|zum|zur|beim|ins|ans|" + DETERMINER + r")")
DETERMINER_RE = re.compile(DETERMINER)
SUBJECT_PRONOUN_RE = re.compile(r"(?:ich|du|er|sie|es|wir|ihr|man)")
RIGHT_WORD_RE = re.compile(r"[^\W\d_]+")
LAST_WORD_RE = re.compile(r"[^\W\d_]+(?=\W*\Z)")
ADJECTIVE_ENDING_RE = re.compile(r"(?:e|en|er|es|em)\Z")
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


def _word_item_count(sentence: str) -> int:
    """Leave items that end or start in a digit to the number count, because each item counts once."""
    commas = list(LIST_COMMA_RE.finditer(sentence))
    infinitives = _lists_infinitives(sentence, commas)
    ends = [*(comma.start() for comma in commas[1:]), len(sentence)]
    closes = (LIST_CLOSE_RE.search(sentence, comma.end(), end) for comma, end in zip(commas, ends))
    edges = [sentence[comma.start() - 1:comma.start()] for comma in commas]
    edges.extend(edge for close in closes if close for edge in _closure_edges(sentence, close, infinitives))
    return sum(not edge.isdigit() for edge in edges)


def _lists_infinitives(sentence: str, commas: list[re.Match[str]]) -> bool:
    """Read the word before each list comma, because only a list of bare infinitives makes a closing -en form an item."""
    starts = [0, *(comma.end() for comma in commas[:-1])]
    befores = [_word_before(sentence, start, comma.start()) for start, comma in zip(starts, commas)]
    return bool(befores) and all(found and found.group(0)[0].islower() and is_infinitive(found.group(0)) for found in befores)


def _word_before(sentence: str, start: int, end: int) -> re.Match[str] | None:
    """From the previous comma first, because a search from 0 for every comma grows with the square of the text."""
    return LAST_WORD_RE.search(sentence, start, end) or LAST_WORD_RE.search(sentence, 0, start)


def _finite_here(word: str, infinitives: bool) -> bool:
    return is_finite(word) and not (infinitives and is_infinitive(word))


def _verb_slot(words: list[str], index: int, infinitives: bool) -> bool:
    """Skip a word after a preposition or determiner, because a finite verb never directly follows one."""
    word, before = words[index], words[index - 1]
    if not word[0].islower() or NOT_VERB_SLOT_RE.fullmatch(word) or NOT_VERB_SLOT_RE.fullmatch(before):
        return False
    return _finite_here(word, infinitives)


def _starts_subject(verb: str, word: str) -> bool:
    """Accept a bare capital only after a verb without an adjective ending, because frischen Saft names one more item."""
    if DETERMINER_RE.fullmatch(word) or SUBJECT_PRONOUN_RE.fullmatch(word):
        return True
    return word[0].isupper() and ADJECTIVE_ENDING_RE.search(verb) is None


def _fronted_verb(words: list[str], infinitives: bool) -> bool:
    """Need a subject right after a leading verb, because a bare infinitive such as bügeln stays a list item."""
    return len(words) > 1 and words[0][0].islower() and _starts_subject(*words[:2]) and _finite_here(words[0], infinitives)


def _opens_clause(right: str, infinitives: bool) -> bool:
    """Need a subject pronoun or a finite verb, because und also opens a clause such as heute kommt der Fahrer."""
    words = RIGHT_WORD_RE.findall(right)
    if not words:
        return False
    if SUBJECT_PRONOUN_RE.fullmatch(words[0]) or _fronted_verb(words, infinitives):
        return True
    return any(_verb_slot(words, index, infinitives) for index in range(1, len(words)))


def _closure_edges(sentence: str, close: re.Match[str], infinitives: bool) -> tuple[str, ...]:
    """Count the side after und only when it is an item, because und also joins a new clause."""
    right = CLOSE_RIGHT_RE.match(sentence, close.start(2)).group(0)
    return close.groups()[:1] if _opens_clause(right, infinitives) else close.groups()


def _information_cluster(sentence: str) -> re.Match[str] | None:
    """Count list items and numbers only, because German capitalizes every noun and hides proper names."""
    items = _word_item_count(sentence) + len(NUMBER_RE.findall(sentence))
    return WHOLE_SENTENCE_RE.search(sentence) if items > CLUSTER_MAX_ITEMS else None


def _is_staccato(sentence: str) -> bool:
    return sentence.rstrip().endswith("!") and len(re.findall(r"\w+", sentence)) <= STACCATO_MAX_WORDS


def _run_hit(paragraph: ParagraphLanguage, offset: int, run: list[re.Match[str]]) -> Hit:
    snippet = " ".join(found.group(0).strip() for found in run)
    span = (offset + run[0].start(), offset + run[-1].end())
    return placed(paragraph, span, Hit(EXCLAMATION_STACCATO.name, paragraph.line, snippet, run[0].group(0).strip()))


def _unit_runs(paragraph: ParagraphLanguage, unit: tuple[int, str]) -> list[Hit]:
    offset, text = unit
    # Ends at the last mark, because a tail without one makes every start rescan it.
    end = max(text.rfind(mark) for mark in ".!?") + 1
    grouped = groupby(STACCATO_SENTENCE_RE.finditer(text, 0, end), key=lambda found: _is_staccato(found.group(0)))
    runs = [list(group) for staccato, group in grouped if staccato]
    return [_run_hit(paragraph, offset, run) for run in runs if len(run) >= STACCATO_MIN_RUN]


def _staccato_runs(paragraph: ParagraphLanguage) -> list[Hit]:
    """Start a run afresh in each text, because exclamations in separate cells are not one staccato."""
    return [hit for unit in text_units(paragraph) for hit in _unit_runs(paragraph, unit)]


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
