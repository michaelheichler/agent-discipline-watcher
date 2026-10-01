"""Leave detection to the vote, because no word list separates these style patterns from correct German (catalog SEMANTIC rows)."""
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
)
STOCK_PHRASE = Rule(
    "de_stock_phrase",
    Wording(
        "German stock phrase",
        "Flags a worn German phrase or dead image, like eine Lanze brechen, that fills space without meaning",
        "Replace the phrase with the plain statement it stands for.",
    ),
    Wording(
        "Abgegriffene Floskel",
        "Meldet eine abgenutzte Wendung oder ein totes Bild wie eine Lanze brechen, das nur Platz füllt",
        "Ersetz die Floskel durch die schlichte Aussage dahinter.",
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
)

RULE_SET = RuleSet(
    rules=(
        PASSIVE_VOICE, STOCK_PHRASE, DICHOTOMY_TEMPLATE, SHALLOW_PARTICIPLE, SYNONYM_ROTATION,
        FAKE_ANALYSIS_TAIL, COMPARATIVE_FRAMING, REGISTER_COLLAPSE, STYLE_SHIFT, FRAGMENT_HEADING,
        RHETORICAL_QUESTION, MARKERLESS_CLOSER, RETROACTIVE_NUANCE,
    ),
    voted=True,
)
