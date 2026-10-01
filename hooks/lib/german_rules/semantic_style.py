"""Leave the verdict to the judge, because no word list separates these style patterns from correct German (catalog SEMANTIC rows)."""
from __future__ import annotations

try:
    from . import Rule, RuleSet, Wording
except ImportError:
    from german_rules import Rule, RuleSet, Wording

PASSIVE_VOICE = Rule(
    "de_passive_voice",
    Wording(
        "German passive hides the actor",
        "Flags a German passive with werden or sein plus participle where the missing actor matters",
        "Name the actor and use an active verb.",
    ),
    Wording(
        "Passiv verschweigt den Handelnden",
        "Meldet ein Passiv mit werden oder sein und Partizip, bei dem der fehlende Handelnde zählt",
        "Nenn den Handelnden und nimm ein aktives Verb.",
    ),
    trigger=r"\b(?:wird|werden|wurde|wurden|worden)\b",
)
STOCK_PHRASE = Rule(
    "de_stock_phrase",
    Wording(
        "German stock phrase",
        "Flags a listed German stock phrase or a dead image like den Weg ebnen that one plain word replaces",
        "Replace the phrase with the plain statement it stands for.",
    ),
    Wording(
        "Abgegriffene Floskel",
        "Meldet eine Floskel aus der Liste oder ein totes Bild wie den Weg ebnen, das ein schlichtes Wort ersetzt",
        "Ersetz die Floskel durch die schlichte Aussage dahinter.",
    ),
    boundary=(
        "Verstoß ist eine Wendung aus den Floskellisten, etwa diesbezüglich, nichtsdestotrotz, unter Zuhilfenahme, "
        "in der heutigen Zeit oder Welt, seit Anbeginn der Zeit. Verstoß ist auch ein totes Bild, also eine bildhafte "
        "feste Wendung, deren Bild niemand mehr sieht und die ein schlichtes Wort ohne Verlust ersetzt, etwa ins Leben "
        "rufen für gründen, den Weg ebnen für ermöglichen, unter die Lupe nehmen für prüfen, im Fokus stehen, ein "
        "Meilenstein, ein Zeichen setzen, eine Lanze brechen, auf Augenhöhe. Sauber sind feste Wendungen ohne Bild wie "
        "nach wie vor, nicht zuletzt, in der Regel. Sauber sind Funktionsverbgefüge wie unter Beweis stellen oder in "
        "Vergessenheit geraten, die eine eigene Regel prüft. Sauber ist jedes Wort in wörtlicher Bedeutung, etwa der "
        "Weg zum Heim oder der Sturm im Fußball."
    ),
    trigger=(
        r"\b(?:nach wie vor|unter die Lupe|im Fokus|Hand in Hand|auf Augenhöhe|in aller Munde|ins Leben gerufen"
        r"|unter Beweis|an Bedeutung gewinn\w*|den Grundstein|Meilenstein|Dreh- und Angelpunkt|Schritt halten"
        r"|Weichen|auf der Hand|an einem Strang|nicht zuletzt|in den Startlöchern|auf Hochtouren|im Mittelpunkt"
        r"|ein Zeichen|den Weg|eine Lanze|im Endeffekt|diesbezüglich|nichtsdestotrotz|in der heutigen)\b"
    ),
)
DICHOTOMY_TEMPLATE = Rule(
    "de_dichotomy_template",
    Wording(
        "German praise and challenge template",
        "Flags the German template Trotz X steht Y vor Z that sets praise against challenges and an outlook",
        "State the one finding that matters, with its evidence.",
    ),
    Wording(
        "Schablone aus Lob und Herausforderung",
        "Meldet die Schablone Trotz X steht Y vor Z, die Lob, Herausforderung und Ausblick gegeneinanderstellt",
        "Nenn den einen Befund, der zählt, mit seinem Beleg.",
    ),
    trigger=r"\btrotz\b|Herausforderung",
)
SHALLOW_PARTICIPLE = Rule(
    "de_shallow_participle",
    Wording(
        "German participle tail as analysis",
        "Flags a German sentence that ends in a participle tail like gewährleistend or hervorhebend posing as analysis",
        "Cut the tail or state the consequence as its own sentence.",
    ),
    Wording(
        "Partizip als Scheinanalyse",
        "Meldet einen Satz, der mit einem Partizip wie gewährleistend oder hervorhebend eine Analyse vortäuscht",
        "Streich das Partizip oder nenn die Folge in einem eigenen Satz.",
    ),
    trigger=r",\s*(?:\w+\s+){0,3}(?!während\b)\w+end\b[.,]?\s*$|,\s*\w+end\b,",
)
SYNONYM_ROTATION = Rule(
    "de_synonym_rotation",
    Wording(
        "German synonym rotation",
        "Flags German text that renames one entity in each sentence, like die Hansestadt and then die Elbmetropole",
        "Keep one name for the entity throughout.",
    ),
    Wording(
        "Wechselnde Namen für dieselbe Sache",
        "Meldet Text, der dieselbe Sache in jedem Satz anders nennt, etwa die Hansestadt und dann die Elbmetropole",
        "Bleib bei einem Namen für dieselbe Sache.",
    ),
    trigger=(
        r"\b(?:die|der|das)\s+(?:\w+-)?(?:Metropole|Hansestadt|Hauptstadt|Konzern|Riese|Gigant|Hersteller"
        r"|Sängerin|Sänger|Schauspieler\w*|Musiker\w*|Künstler\w*|Politiker\w*|Verein|Klub|Club|Mannschaft|Elf)\b"
    ),
)
FAKE_ANALYSIS_TAIL = Rule(
    "de_fake_analysis_tail",
    Wording(
        "German fake analysis tail",
        "Flags a German relative clause tail like was X unterstreicht that adds no new information",
        "Delete the tail or replace it with the fact it hints at.",
    ),
    Wording(
        "Angehängte Scheinanalyse",
        "Meldet einen Relativsatz am Ende wie was X unterstreicht, der keine neue Information bringt",
        "Streich den Anhang oder ersetz ihn durch die Tatsache dahinter.",
    ),
    trigger=r",\s*(?:was|wodurch|womit)\b",
)
COMPARATIVE_FRAMING = Rule(
    "de_comparative_framing",
    Wording(
        "German comparative framing",
        "Flags the German frame weniger X als vielmehr Y that stands in for a plain description",
        "Describe Y directly.",
    ),
    Wording(
        "Rahmen weniger X als vielmehr Y",
        "Meldet den Rahmen weniger X als vielmehr Y, wo eine schlichte Beschreibung reicht",
        "Beschreib Y direkt.",
    ),
    trigger=r"\b(?:vielmehr|nicht so sehr|weniger\b[^.]{1,40}\bals)\b",
)
REGISTER_COLLAPSE = Rule(
    "de_register_collapse",
    Wording(
        "German register collapse",
        "Flags a casual German particle inside an otherwise formal sentence and paragraph",
        "Keep one register for the whole passage.",
    ),
    Wording(
        "Bruch im Sprachregister",
        "Meldet eine lockere Partikel in einem sonst förmlichen Satz und Absatz",
        "Halte ein Sprachregister im ganzen Abschnitt.",
    ),
    trigger=r"\b(?:halt|mal|eh|echt|krass|total|super|cool|okay)\b|\w\s+(?:ja|doch|eben)\b",
)
STYLE_SHIFT = Rule(
    "de_style_shift",
    Wording(
        "German style shift",
        "Flags German paragraphs that read as if different authors wrote them",
        "Rewrite the passage in one voice.",
    ),
    Wording(
        "Stilwechsel zwischen Absätzen",
        "Meldet Absätze, die klingen, als hätten verschiedene Autoren sie geschrieben",
        "Schreib den Abschnitt mit einer Stimme.",
    ),
)
FRAGMENT_HEADING = Rule(
    "de_fragment_heading",
    Wording(
        "German slogan under a heading",
        "Flags a generic one-line German sentence like Geschwindigkeit zählt. right under a heading",
        "Delete the line and start with the content.",
    ),
    Wording(
        "Merksatz unter der Überschrift",
        "Meldet einen allgemeinen Einzeiler wie Geschwindigkeit zählt. direkt unter einer Überschrift",
        "Streich die Zeile und beginn mit dem Inhalt.",
    ),
)
RHETORICAL_QUESTION = Rule(
    "de_rhetorical_question",
    Wording(
        "German rhetorical question",
        "Flags a German question like Aber was bedeutet das? that the text asks only to answer itself",
        "Delete the question and state the answer.",
    ),
    Wording(
        "Rhetorische Frage als Köder",
        "Meldet eine Frage wie Aber was bedeutet das?, die der Text nur stellt, um sie selbst zu beantworten",
        "Streich die Frage und nenn die Antwort.",
    ),
    trigger=r"\?$",
)
MARKERLESS_CLOSER = Rule(
    "de_markerless_closer",
    Wording(
        "German evaluative closer",
        "Flags an evaluative German sentence at the end of a paragraph that adds no new fact",
        "End the paragraph after the last fact.",
    ),
    Wording(
        "Wertender Schlusssatz",
        "Meldet einen wertenden Satz am Absatzende, der keine neue Tatsache bringt",
        "Beende den Absatz nach der letzten Tatsache.",
    ),
    trigger=r"\b(?:insgesamt|zeigt|bleibt|wichtig\w*|Bedeutung|beeindruckend\w*|spannend\w*|Zukunft|deutlich)\b",
)
RETROACTIVE_NUANCE = Rule(
    "de_retroactive_nuance",
    Wording(
        "German fake nuance",
        "Flags a German Genauer gesagt or Fairerweise that repeats the previous claim in softer words",
        "Keep the precise version and delete the first one.",
    ),
    Wording(
        "Nachgeschobene Scheinnuance",
        "Meldet ein Genauer gesagt oder Fairerweise, das die vorige Aussage nur weicher wiederholt",
        "Behalte die genaue Fassung und streich die erste.",
    ),
    boundary=(
        "Verstoß nur, wenn eine Präzisierungsformel wie genauer gesagt, besser gesagt, anders gesagt, mit anderen "
        "Worten, fairerweise, streng genommen, genau genommen oder eigentlich ist es komplizierter eine eben gemachte "
        "Aussage wiederholt und dabei keine neue Bedingung, Teilmenge, Ursache, Zahl, Ausnahme oder Gegenposition nennt. "
        "Sauber ist eigentlich als Partikel oder im Sinn von ursprünglich, geplant, laut Regel. Sauber ist genauer als "
        "Komparativ oder Adjektiv, etwa genauer untersuchen oder der genaue Standort. Sauber ist jede Formel, nach der "
        "eine echte neue Angabe folgt, etwa Genauer gesagt bestanden 12 von 15 Prüffällen."
    ),
    trigger=(
        r"\b(?:genauer|fairerweise|eigentlich|streng genommen|genau genommen|besser gesagt|anders gesagt"
        r"|mit anderen Worten)\b"
    ),
)

RULE_SET = RuleSet(
    rules=(
        PASSIVE_VOICE, STOCK_PHRASE, DICHOTOMY_TEMPLATE, SHALLOW_PARTICIPLE, SYNONYM_ROTATION,
        FAKE_ANALYSIS_TAIL, COMPARATIVE_FRAMING, REGISTER_COLLAPSE, STYLE_SHIFT, FRAGMENT_HEADING,
        RHETORICAL_QUESTION, MARKERLESS_CLOSER, RETROACTIVE_NUANCE,
    ),
    voted=True,
)
