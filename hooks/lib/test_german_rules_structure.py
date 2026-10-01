"""Each German structure and rhetoric rule fires on its bad example and stays quiet on its good one, because a rule that fires on clean text trains writers to ignore it."""
from __future__ import annotations

import pytest

from lib import german_rules
from lib.prose_language import ParagraphLanguage

VIOLATING = [
    ("de_nested_clauses", "Der Bericht, der von der Abteilung, die für die Auswertung zuständig ist, vor zwei Wochen fertiggestellt wurde, liegt jetzt vor."),
    ("de_verb_bracket", "Die oberen Räume muss der Pförtner zum Ende der Veranstaltung, spätestens aber wenn der Trainer das Gebäude verlassen hat, schließen."),
    ("de_verb_bracket", "Er hat das Buch, das ich ihm gestern gegeben habe, gelesen."),
    ("de_unexplained_abbreviation", "Wir liefern usw. alle Teile, bzw. die noch fehlenden Stücke, d.h. bis Freitag."),
    ("de_exclamation_staccato", "Endlich da! Das neue Sonderheft! Jetzt zugreifen!"),
    ("de_casual_greeting", "Tachchen Herr Schmidt, Ihre Bestellung ist da."),
    ("de_casual_greeting", "Ihre Bestellung ist da. So long!"),
    ("de_information_cluster", "Der Kunde bestellte die Artikel 4471, 4472 und 4473 in den Farben Rot, Blau, Grün und Gelb, lieferbar am Montag, Mittwoch oder Freitag über DHL, Hermes oder die Deutsche Post."),
    ("de_triad", "Die Wirtschaft war vielfältig, kreativ und widerstandsfähig."),
    ("de_authority_phrase", "Die eigentliche Frage ist, ob Teams sich anpassen können."),
    ("de_signposting", "Schauen wir uns an, wie Caching funktioniert."),
    ("de_aphorism_formula", "Symmetrie ist die Sprache des Vertrauens."),
    ("de_announcing_cleft", "Was mich überrascht hat, war die Ladezeit. Was fehlte, war ein Cache."),
]

CLEAN = [
    ("de_nested_clauses", "Die Abteilung für Auswertung hat den Bericht vor zwei Wochen fertiggestellt. Er liegt jetzt vor."),
    ("de_nested_clauses", "Wir prüfen Rot, Blau, Grün, Gelb und Weiß, weil der Kunde es wünscht."),
    ("de_verb_bracket", "Die oberen Räume muss der Pförtner schließen, wenn die Veranstaltung endet oder der Trainer das Gebäude verlässt."),
    ("de_verb_bracket", "Wir müssen klären, ob die Kollegen aus dem Vertrieb morgen früh kommen."),
    ("de_unexplained_abbreviation", "Wir liefern alle Teile und die noch fehlenden Stücke bis Freitag an die GmbH."),
    ("de_exclamation_staccato", "Das neue Sonderheft ist endlich da. Jetzt am Kiosk."),
    ("de_casual_greeting", "Sehr geehrter Herr Schmidt, Ihre Bestellung ist da. Mit freundlichen Grüßen."),
    ("de_casual_greeting", "Hin und wieder prüfen wir die Liste."),
    ("de_information_cluster", "Der Kunde bestellte die Artikel 4471, 4472 und 4473 in Rot, Blau, Grün und Gelb. Die Lieferung erfolgt an einem von drei Tagen."),
    ("de_triad", "Die Wirtschaft war kreativ und widerstandsfähig."),
    ("de_triad", "Das Team war klein, schnell, mutig und laut."),
    ("de_authority_phrase", "Ob Teams sich anpassen können, hängt von der Bereitschaft ab."),
    ("de_authority_phrase", "Im Kern des Reaktors steigt die Temperatur."),
    ("de_signposting", "Caching speichert Antworten zwischen. Lass uns morgen sprechen."),
    ("de_aphorism_formula", "Symmetrie kann Vertrauen fördern."),
    ("de_announcing_cleft", "Die Ladezeit hat mich überrascht. Was du brauchst, ist ein Cache."),
]


def _fired(text: str) -> set[str]:
    paragraph = ParagraphLanguage(line=1, text=text, language="de", weak=False)
    return {row["rule"] for row in german_rules.check_paragraphs("doc.md", [paragraph])}


@pytest.mark.parametrize(("rule", "text"), VIOLATING)
def test_the_bad_example_raises_its_rule(rule: str, text: str) -> None:
    assert rule in _fired(text)


@pytest.mark.parametrize(("rule", "text"), CLEAN)
def test_the_good_example_stays_quiet(rule: str, text: str) -> None:
    assert rule not in _fired(text)


def test_a_staccato_run_reports_the_line_it_starts_on() -> None:
    paragraph = ParagraphLanguage(line=4, text="Der Plan steht.\nEndlich da! Neu! Jetzt kaufen!", language="de", weak=False)

    rows = german_rules.check_paragraphs("doc.md", [paragraph])

    assert [(row["line"], row["snippet"]) for row in rows if row["rule"] == "de_exclamation_staccato"] == [
        (5, "Endlich da! Neu! Jetzt kaufen!"),
    ]
