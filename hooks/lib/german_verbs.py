"""Read a finite verb from dictionary stems and regular endings, because only a finite verb makes the words after und a clause."""
from __future__ import annotations

import gzip
import json
from functools import cache
from pathlib import Path
from typing import NamedTuple

VERBS_PATH = Path(__file__).with_name("german_verbs.json.gz")
FINITE_ENDINGS = ("t", "et", "en", "te", "ten", "ete", "eten")
PARTICIPLE_ENDINGS = ("t", "et", "en")
IRREGULAR_FINITE = frozenset("""
bin bist ist sind seid war warst waren wart habe hast hat habt hatte hattest hatten hattet
werde wirst wird werdet wurde wurdest wurden wurdet tut tat taten
kann kannst könnt konnte konnten muss musst müsst musste mussten darf darfst dürft durfte durften
soll sollst sollt sollte sollten will willst wollt wollte wollten mag magst mögt mochte mochten möchte möchten
weißt wisst wusste wussten gibt nimmt sieht liest fährt läuft hält lässt fällt trägt schläft spricht hilft
trifft isst wirft wächst gilt stirbt vergisst bricht empfiehlt stiehlt tritt brät rät lädt
kam kamen ging gingen gab gaben sah sahen stand standen lag lagen blieb blieben fuhr fuhren lief liefen
nahm nahmen hielt hielten ließ ließen fand fanden rief riefen sprach sprachen trug trugen fiel fielen
zog zogen saß saßen schrieb schrieben bot boten bat baten brachte brachten dachte dachten kannte kannten
nannte nannten rannte rannten schien schienen hing hingen traf trafen warf warfen half halfen las lasen
trat traten wuchs wuchsen starb starben
""".split())


class VerbData(NamedTuple):
    stems: frozenset[str]
    not_finite: frozenset[str]


@cache
def _verb_data() -> VerbData:
    with gzip.open(VERBS_PATH, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    return VerbData(frozenset(data["stems"]), frozenset(data["not_finite"]))


def regular_finite(word: str, stems: frozenset[str]) -> bool:
    return any(word.endswith(ending) and word[:-len(ending)] in stems for ending in FINITE_ENDINGS)


def _participle(word: str, stems: frozenset[str]) -> bool:
    """Read ge plus a verb stem plus t or en as a participle, because hausgemacht after a noun is no verb."""
    return any(
        word[index + 2:len(word) - len(ending)] in stems
        for index in range(len(word) - 2) if word.startswith("ge", index)
        for ending in PARTICIPLE_ENDINGS if word.endswith(ending)
    )


def is_infinitive(word: str) -> bool:
    stems = _verb_data().stems
    return (word.endswith("en") and word[:-2] in stems) or (word.endswith("n") and word[:-1] in stems)


def is_finite(word: str) -> bool:
    if word in IRREGULAR_FINITE:
        return True
    data = _verb_data()
    return word not in data.not_finite and regular_finite(word, data.stems) and not _participle(word, data.stems)
