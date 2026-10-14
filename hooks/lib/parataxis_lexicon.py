"""Kept apart from parataxis.py, because the word lists change with calibration while the run logic does not."""
from __future__ import annotations

import re
from typing import NamedTuple

ENGLISH_RULE = "choppy_sentences"
GERMAN_RULE = "de_parataxis"


class Lexicon(NamedTuple):
    rule: str
    joiners: frozenset[str]
    joining_re: re.Pattern[str] | None
    back_references: frozenset[str]
    articles: frozenset[str]
    fronted: frozenset[str]
    min_lowercase_share: float
    max_ordinal_digits: int


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


ENGLISH = Lexicon(
    ENGLISH_RULE,
    _words(
        "because since although though while whereas when whenever where wherever if unless until till "
        "after before once as so that which who whom whose whether and but or nor yet than without"
    ),
    None,
    _words("it this that these those they he she its their his her such"),
    frozenset(),
    _words(
        "in on at by for from with without after before during since under over through into onto about "
        "against among between within across toward towards then now here there today later soon still "
        "also however instead finally first next meanwhile thus therefore sometimes often usually perhaps "
        "maybe only even again never always"
    ),
    0.5,
    0,
)
# Narrow, because a preposition like seit or bis joins no clause.
GERMAN = Lexicon(
    GERMAN_RULE,
    _words(
        "und oder aber sondern denn doch sowie weil obwohl obgleich obschon sodass dass daß nachdem bevor "
        "ehe wenn falls sofern ob indem sobald solange sooft wobei weshalb weswegen zumal"
    ),
    re.compile(r"\bzu [a-zäöüß]+en\b|\b(?:um|ohne|statt|anstatt)\b.*\bzu\b"),
    _words(
        "er sie es das dies diese dieser dieses diesen der die dessen deren sein seine seinen seiner "
        "ihr ihre ihren ihrer"
    ),
    _words("der die das"),
    _words(
        "in im am an auf aus bei beim mit nach von vom zum zur zu vor über unter durch für gegen ohne um seit "
        "bis ab während wegen trotz neben hinter zwischen innerhalb außerhalb gemäß laut dann danach dabei "
        "dadurch damit daher deshalb deswegen trotzdem dennoch jedoch also so hier dort heute jetzt nun "
        "später zuvor zunächst anschließend schließlich außerdem zudem ebenfalls auch noch bereits schon "
        "immer oft manchmal möglicherweise vielleicht lediglich nur erst ebenso stattdessen"
    ),
    0.0,
    # Because am 3. Oktober is an ordinal, while a year closes a sentence.
    2,
)
# Without usw and etc, because those often close a sentence.
ABBREVIATIONS = _words(
    "st dr mr mrs ms prof nr no vol abb fig jr sr ca bzw vgl evtl ggf inkl bspw sog vs geh bd hrsg bzgl"
)
