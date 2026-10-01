"""Kept apart from catalog.py, because a German paragraph earns German findings while rule ids stay English (decision Q14)."""
from __future__ import annotations

from typing import NamedTuple


class GermanEntry(NamedTuple):
    """Carry the action as well, because the English action text would leave half of a German row untranslated."""

    title: str
    description: str
    action: str


BLOCK_LEAD = "agent-discipline-watcher hat diese Befunde blockiert:"
OBSERVE_LEAD = (
    "agent-discipline-watcher beobachtet diese Befunde und blockiert nicht. "
    "Prüf jeden Befund und behebe ihn oder begründe, warum er bleibt."
)
INHERITED_LEAD = (
    "agent-discipline-watcher: Diese Datei hatte schon {count} Befunde, "
    "die du nicht geschrieben hast. Behebe sie, solange du hier arbeitest."
)
FULL_REPORT = "Vollständiger Bericht"
MORE_FINDINGS = "weitere Befunde"
PRINCIPLE_LABEL = "Prinzip"

RULES: dict[str, GermanEntry] = {
    "banned_dash": GermanEntry(
        "Unzulässiger Strich",
        "Meldet den Geviertstrich und den Halbgeviertstrich ohne Leerzeichen",
        "Nimm einen Bindestrich, ein Komma oder einen Punkt.",
    ),
    "dash_break": GermanEntry(
        "Doppelter Bindestrich als Strich",
        "Meldet zwei Bindestriche, die einen Satz teilen",
        "Setz ein Komma, einen Punkt oder Klammern.",
    ),
    "spaced_hyphen": GermanEntry(
        "Bindestrich mit Leerzeichen",
        "Meldet einen Bindestrich mit Leerzeichen, der einen Gedankenstrich ersetzt",
        "Setz ein Komma oder einen Punkt, oder schließ den Bindestrich an das Wort an.",
    ),
    "pronoun_apostrophe": GermanEntry(
        "Apostroph am Pronomen",
        "Meldet einen Apostroph an einem englischen Possessivpronomen wie your's",
        "Schreib das Possessivpronomen ohne Apostroph.",
    ),
    "decade_apostrophe": GermanEntry(
        "Apostroph am Jahrzehnt",
        "Meldet ein Jahrzehnt wie 1990's mit Apostroph",
        "Schreib das Jahrzehnt ohne Apostroph, etwa „die 1990er“.",
    ),
    "quote_marks": GermanEntry(
        "Anführungszeichen nicht deutsch",
        "Meldet gerade oder englische Anführungszeichen in deutschem Text, der „…“ und ‚…‘ verlangt",
        "Setz die deutschen Paare „…“ oder ‚…‘.",
    ),
    "genitive_apostrophe": GermanEntry(
        "Apostroph im Genitiv",
        "Meldet Peter's in deutschem Text, wo der Genitiv ein bloßes s nimmt",
        "Schreib das Genitiv-s ohne Apostroph.",
    ),
    "typed_ellipsis": GermanEntry(
        "Auslassungspunkte getippt",
        "Meldet drei getippte Punkte oder einen Zusatzpunkt, wo das Deutsche ein einzelnes Zeichen … verlangt",
        "Setz ein einzelnes Zeichen … ohne weiteren Punkt.",
    ),
    "dash_cluster": GermanEntry(
        "Zu viele Gedankenstriche",
        "Meldet deutschen Text, der den Gedankenstrich über die Dichtegrenze hinaus nutzt",
        "Ersetz einige Gedankenstriche durch Komma, Punkt oder Doppelpunkt.",
    ),
    "de_sentence_length": GermanEntry(
        "Deutscher Satz zu lang",
        "Meldet einen deutschen Satz mit mehr als zwanzig Wörtern",
        "Teil den Satz an einer Nebensatzgrenze.",
    ),
    "de_uniform_rhythm": GermanEntry(
        "Gleichförmiger Satzrhythmus",
        "Meldet deutsche Sätze, deren Länge im ganzen Dokument kaum schwankt",
        "Wechsle zwischen kurzen und langen Sätzen.",
    ),
    "de_uniform_paragraphs": GermanEntry(
        "Gleich lange Absätze",
        "Meldet deutsche Absätze, die alle fast gleich lang sind",
        "Mach einige Absätze kürzer oder länger als die übrigen.",
    ),
    "de_repeated_connector": GermanEntry(
        "Gehäufte Satzanschlüsse",
        "Meldet einen Absatz, der mehr als einen Satz mit außerdem, ferner oder einem ähnlichen Wort beginnt",
        "Beginn höchstens einen Satz im Absatz mit einem Wort wie „außerdem“.",
    ),
    "de_long_compound": GermanEntry(
        "Langes Kompositum",
        "Meldet ein deutsches Kompositum ab sechs Silben ohne Bindestrich",
        "Gliedere das Wort mit Bindestrich oder löse es in eine Genitivgruppe auf.",
    ),
    "dead_metaphor": GermanEntry(
        "Abgegriffenes Bild",
        "Streicht ein Standardbild, das nichts Konkretes benennt",
        "Nenn den konkreten Sachverhalt statt des Bildes.",
    ),
    "filler": GermanEntry(
        "Füllphrase",
        "Streicht eine Wendung, die Wörter und keine Bedeutung bringt",
        "Streich die Wendung und sag den Punkt direkt.",
    ),
    "throat_clearing": GermanEntry(
        "Anlauf vor dem Punkt",
        "Streicht einen Einstieg, der den Punkt hinauszögert",
        "Beginn mit dem Punkt.",
    ),
    "filler_opener": GermanEntry(
        "Floskelhafter Einstieg",
        "Streicht einen Einstieg, der eine Szene malt, statt den Punkt zu nennen",
        "Beginn mit der eigentlichen Aussage.",
    ),
    "ai_tell": GermanEntry(
        "Typische KI-Wendung",
        "Streicht eine Wendung, die typisch für generierten Text ist",
        "Nimm ein schlichtes Verb.",
    ),
    "inflated_diction": GermanEntry(
        "Aufgeblähtes Wort",
        "Streicht ein großes Wort, wo ein schlichtes reicht",
        "Nimm das schlichte Wort.",
    ),
    "utilize": GermanEntry(
        "Langes Wort für use",
        "Streicht utilize und seine Formen",
        "Schreib „use“ oder ein schlichtes deutsches Verb.",
    ),
    "wordiness": GermanEntry(
        "Umständliche Wendung",
        "Streicht eine lange Wendung, für die es eine kurze gibt",
        "Nimm die kurze Form.",
    ),
    "vague_quantity": GermanEntry(
        "Vage Mengenangabe",
        "Streicht eine Wendung, die die echte Zahl verdeckt",
        "Nenn die Zahl oder die einzelnen Dinge.",
    ),
    "expletive_there": GermanEntry(
        "Einstieg mit there is",
        "Streicht einen Einstieg mit there is, der das Subjekt versteckt",
        "Beginn mit dem Subjekt und einem aktiven Verb.",
    ),
    "empty_intensifier": GermanEntry(
        "Leerer Verstärker",
        "Streicht einen Verstärker, der Nachdruck und keine Bedeutung bringt",
        "Streich den Verstärker oder wähl ein treffenderes Wort.",
    ),
    "ai_closer": GermanEntry(
        "Floskel zum Abschluss",
        "Streicht die Schlussgeste, die den Punkt wiederholt, statt zu enden",
        "Hör auf, wenn die Antwort fertig ist.",
    ),
    "banned_adverb": GermanEntry(
        "Leere Verstärkerwörter",
        "Streicht really, just, literally, simply, actually und elf weitere Wörter ohne Bedeutung",
        "Streich das Wort.",
    ),
    "binary_contrast": GermanEntry(
        "Rahmen nicht X, sondern Y",
        "Streicht das falsche Entweder-oder, das entschieden klingt und wenig sagt",
        "Nenn die positive Aussage direkt.",
    ),
    "business_jargon": GermanEntry(
        "Konzernvokabular",
        "Streicht navigate the, unpack the, lean into und the X landscape",
        "Nenn die konkrete Handlung.",
    ),
    "corporate_idiom": GermanEntry(
        "Bürofloskel",
        "Streicht eine Redewendung aus dem Büroalltag ohne konkrete Aussage",
        "Nenn die wörtliche Handlung.",
    ),
    "dramatic_fragmentation": GermanEntry(
        "Fragmente für Dramatik",
        "Streicht den Absatz aus einem Wort, der sein Gewicht aus Leerraum zieht",
        "Schreib vollständige Sätze.",
    ),
    "emphasis_crutch": GermanEntry(
        "Künstliche Betonung",
        "Streicht full stop, let that sink in, make no mistake und this matters because",
        "Streich die Betonungsformel.",
    ),
    "false_agency": GermanEntry(
        "Dinge handeln von selbst",
        "Streicht Formulierungen, die einem Ding eine Handlung zuschreiben, die es nicht ausführen kann",
        "Nenn die Person oder die Handlung, die verantwortlich ist.",
    ),
    "filler_phrase": GermanEntry(
        "Einleitende Füllwendung",
        "Streicht at its core, when it comes to, the reality is und in today's X",
        "Streich die Füllwendung.",
    ),
    "formulaic_construction": GermanEntry(
        "Schablonenhafter Satzbau",
        "Streicht die wiederkehrende Satzschablone, die generierten Text verrät",
        "Ersetz die Schablone durch eine direkte Beschreibung.",
    ),
    "formulaic_filler": GermanEntry(
        "Ausgewogenheitsfloskel",
        "Streicht it is important to note, on one hand und first and foremost",
        "Streich die Floskel und sag den Punkt.",
    ),
    "formulaic_opener": GermanEntry(
        "Standarderöffnung",
        "Streicht in a world where, imagine this und whether you are a beginner",
        "Beginn mit der Aussage.",
    ),
    "greeting_opener": GermanEntry(
        "Gruß vor der Antwort",
        "Streicht die Begrüßung, die den ersten nützlichen Satz verzögert",
        "Beginn mit der Antwort.",
    ),
    "hedge_stack": GermanEntry(
        "Gestapelte Einschränkungen",
        "Streicht gehäufte Einschränkungen, die eine Aussage aufweichen, bis sie nichts mehr sagt",
        "Behalte eine Einschränkung oder nenn die Tatsache.",
    ),
    "lazy_extreme": GermanEntry(
        "Absolute Behauptung",
        "Streicht every, always, never und nothing, wo die Aussage nicht absolut gilt",
        "Nenn den tatsächlichen Umfang oder die Zahl.",
    ),
    "long_sentence": GermanEntry(
        "Satz über der Wortgrenze",
        "Meldet einen Satz über der Wortgrenze, die standardmäßig bei 40 Wörtern liegt",
        "Teil den Satz in zwei Sätze.",
    ),
    "low_sentence_variance": GermanEntry(
        "Gleich lange Sätze",
        "Meldet Text, in dem jeder Satz gleich lang ist",
        "Wechsle zwischen kurzen und langen Sätzen.",
    ),
    "meta_commentary": GermanEntry(
        "Bemerkung über das Schreiben",
        "Streicht hint, plot twist, spoiler und is a feature not a bug",
        "Streich die Bemerkung.",
    ),
    "narrator_distance": GermanEntry(
        "Erzähler tritt zurück",
        "Streicht den Schritt, der das Thema kommentiert, statt es zu benennen",
        "Nenn die Menschen oder sprich den Leser direkt an.",
    ),
    "negative_listing": GermanEntry(
        "Bestimmung durch Verneinung",
        "Streicht die Reihe von Verneinungen, die nichts Konkretes beschreibt",
        "Nenn den Punkt ohne Anlauf.",
    ),
    "oversized_list": GermanEntry(
        "Liste zu lang zum Überfliegen",
        "Meldet eine Liste über der Höchstzahl, die standardmäßig bei 8 Punkten liegt",
        "Kürz die Liste oder teil sie in Gruppen.",
    ),
    "passive_voice": GermanEntry(
        "Passiv versteckt den Handelnden",
        "Fragt nach dem Handelnden und einem aktiven Verb statt des Passivs",
        "Nenn den Handelnden und nimm ein aktives Verb.",
    ),
    "performative_emphasis": GermanEntry(
        "Gespielte Aufrichtigkeit",
        "Streicht creeps in, they exist I promise und I promise",
        "Streich die Beteuerung.",
    ),
    "rhetorical_setup": GermanEntry(
        "Frage nur zum Beantworten",
        "Streicht die rhetorische Frage, die einen laufenden Punkt inszeniert",
        "Streich die Frage und nenn die Aussage.",
    ),
    "telling_not_showing": GermanEntry(
        "Behaupten statt zeigen",
        "Streicht this is genuinely hard und actually matters anstelle von Belegen",
        "Zeig den Beleg statt der Behauptung.",
    ),
    "three_item_list": GermanEntry(
        "Dreierrhythmus",
        "Gibt die Dreierreihe an einen Prüfer, weil drei Punkte echt oder ein Taktmuster sein können",
        "Behalte die Dreierreihe nur, wenn es genau drei Punkte gibt.",
    ),
    "throat_clearing_opener": GermanEntry(
        "Aufwärmen vor dem Punkt",
        "Streicht here is the thing, it turns out und the real X is",
        "Beginn mit dem Punkt.",
    ),
    "uniform_paragraph_endings": GermanEntry(
        "Absätze enden gleich",
        "Meldet Text, in dem Absatz um Absatz gleich endet",
        "Lass die Absätze unterschiedlich enden.",
    ),
    "vague_declarative": GermanEntry(
        "Große Aussage ohne Inhalt",
        "Streicht the reasons are structural und the implications are significant",
        "Nenn die konkreten Gründe oder Folgen.",
    ),
    "weak_sentence_starter": GermanEntry(
        "Verstecktes Subjekt",
        "Streicht Einstiege mit there is und it is, die das echte Subjekt nach hinten schieben",
        "Beginn mit dem Subjekt oder dem Verb.",
    ),
    "weighted_slop_marker": GermanEntry(
        "Zu viele KI-Marker",
        "Meldet Text, in dem sich gewichtete Marker für generierten Text über der Schwelle häufen",
        "Ersetz die markierten Wörter durch schlichte.",
    ),
}
