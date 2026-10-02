"""Leave the verdict to the judge, because judging a claim against its evidence needs context no word list holds (catalog SEMANTIC rows)."""
from __future__ import annotations

try:
    from . import Rule, RuleSet, Wording
except ImportError:
    from german_rules import Rule, RuleSet, Wording

CITATION_CUE = r"\b(?:ISBN|DOI|et al|Journal|Zeitschrift|veröffentlicht|laut (?:einer|der|dem) (?:Studie|Bericht|Umfrage))\b|\(\d{4}\)"

UNEXPLAINED_FOREIGN_WORD = Rule(
    "de_unexplained_foreign_word",
    Wording(
        "German unexplained foreign word",
        "Flags an English word in German text that is no established loanword and has no gloss",
        "Use the German word or explain the term at first use.",
    ),
    Wording(
        "Fremdwort ohne Erklärung",
        "Meldet ein englisches Wort ohne Erklärung, das kein eingebürgertes Lehnwort ist",
        "Nimm das deutsche Wort oder erklär den Begriff beim ersten Auftreten.",
    ),
    boundary=(
        "Wie humanizer-de: Fachbegriffe, Titel, Namen und eingebürgerte Lehnwörter sind sauber. Eingebürgert ist ein "
        "Wort, das eine Tageszeitung ohne Erklärung druckt, etwa Team, Feedback, Tool, Feature, Community, Statement, "
        "Performance, Release, Engagement, Lifestyle, Highlight, Content, Blog, Design, Software. Im Zweifel gilt ein "
        "einzelnes Lehnwort als eingebürgert. Verstoß ist ein englisches Wort oder eine englische Wendung, die ein "
        "allgemeines Publikum nicht sicher versteht, ohne Erklärung daneben, etwa Sense and Simplicity Ansatz, "
        "Anchor-Woman, Slutification. Eine Erklärung durch Beispiele oder nach dem Doppelpunkt macht den Satz sauber."
    ),
    trigger=(
        r"\b(?:Tools?|Features?|Workflow|Insights?|Mindset|Skills|Content|Commitment|Challenge|Performance"
        r"|Deadline|Feedback|Use Case|Stakeholder|Benefits?|Lifestyle|Highlights?|Community|Influencer"
        r"|Branding|Engagement|Impact|Framework|Roadmap|Comeback|Lockdown|Statement|Hype|Release)\b"
    ),
)
UNBACKED_SUPERLATIVE = Rule(
    "de_unbacked_superlative",
    Wording(
        "German superlative without evidence",
        "Flags a German superlative or absolute claim with no source, date, or named opinion beside it",
        "Name the source or the person who holds the opinion, or drop the superlative.",
    ),
    Wording(
        "Superlativ ohne Beleg",
        "Meldet einen Superlativ oder eine absolute Aussage ohne Quelle, Datum oder benannte Meinung daneben",
        "Nenn die Quelle oder die Person mit dieser Meinung, oder streich den Superlativ.",
    ),
    trigger=r"\b(?:(?:am|der|die|das|den|dem|des)\s+\w+(?:st|ßt)e[nmrs]?|\w*(?:beste|einzige|immer|niemals)\w*)\b",
    state="off",
)
VAGUE_AUTHORITY = Rule(
    "de_vague_authority",
    Wording(
        "German vague authority",
        "Flags a German appeal like Branchenberichte zeigen or Manche argumentieren that names no source",
        "Name the report or the person, or cut the appeal.",
    ),
    Wording(
        "Berufung auf vage Autorität",
        "Meldet Berufungen wie Branchenberichte zeigen oder Manche argumentieren ohne genannte Quelle",
        "Nenn den Bericht oder die Person, oder streich die Berufung.",
    ),
    trigger=(
        r"\b(?:Experten|Studien|Berichte|Kritiker|Manche|Einige|viele Menschen|Beobachter|Analysten|Fachleute"
        r"|es heißt)\b"
    ),
)
FALSE_RANGE = Rule(
    "de_false_range",
    Wording(
        "German false range",
        "Flags a German span like von traditionellen bis modernen that spans no real scale",
        "List the actual items instead of the span.",
    ),
    Wording(
        "Scheinbare Spannweite",
        "Meldet Spannen wie von traditionellen bis modernen, hinter denen keine echte Skala steht",
        "Zähl die tatsächlichen Dinge auf statt der Spanne.",
    ),
    trigger=r"\bvon\b[^,.]{1,40}\bbis\b",
)
BROKEN_LINK = Rule(
    "de_broken_link",
    Wording(
        "German text with a dead link",
        "Flags a link in German text that points to a missing page or article",
        "Replace the link with a working source or remove it.",
    ),
    Wording(
        "Toter Link",
        "Meldet einen Link, der auf eine fehlende Seite oder einen fehlenden Artikel zeigt",
        "Ersetz den Link durch eine erreichbare Quelle oder entfern ihn.",
    ),
    trigger=r"https?://|www\.",
)
FABRICATED_CITATION = Rule(
    "de_fabricated_citation",
    Wording(
        "German fabricated citation",
        "Flags an invented source, an invalid DOI or ISBN, or a source that does not exist",
        "Cite a source you have checked, or remove the citation.",
    ),
    Wording(
        "Erfundene Quelle",
        "Meldet eine erfundene Quelle, eine ungültige DOI oder ISBN oder eine Quelle, die es nicht gibt",
        "Zitier eine geprüfte Quelle oder streich das Zitat.",
    ),
    trigger=CITATION_CUE,
)
EPISTEMIC_MISCALIBRATION = Rule(
    "de_epistemic_miscalibration",
    Wording(
        "German overclaim mixed with overhedge",
        "Flags German text that pairs words like grundlegend with hedges like scheint möglicherweise",
        "State how sure the evidence makes you, once.",
    ),
    Wording(
        "Übertreibung neben Absicherung",
        "Meldet Text, der Wörter wie grundlegend mit Absicherungen wie scheint möglicherweise mischt",
        "Sag einmal, wie sicher der Beleg dich macht.",
    ),
    trigger=(
        r"\b(?:grundlegend|entscheidend|zweifellos|unbestreitbar|enorm|revolution\w*|bahnbrechend|scheint"
        r"|möglicherweise|vielleicht|eventuell)\b"
    ),
    state="off",
)
GAP_FILLING_SPECULATION = Rule(
    "de_gap_filling_speculation",
    Wording(
        "German speculation over a missing source",
        "Flags a German guess like hält sich bedeckt or vermutlich that covers a missing source",
        "Say that the source is missing, or find it.",
    ),
    Wording(
        "Vermutung statt Quelle",
        "Meldet Vermutungen wie hält sich bedeckt oder vermutlich, die eine fehlende Quelle überdecken",
        "Sag, dass die Quelle fehlt, oder such sie.",
    ),
    trigger=r"\b(?:vermutlich|wahrscheinlich|wohl|angeblich|offenbar|unklar|spekuliert|Gerüchte?|bedeckt)\b",
)
INVENTED_ANECDOTE = Rule(
    "de_invented_anecdote",
    Wording(
        "German staged first-person anecdote",
        "Flags a staged German first-person story with Ehrlich gesagt or Spoiler and no real narrator",
        "Delete the anecdote and state the fact.",
    ),
    Wording(
        "Erfundene Ich-Erfahrung",
        "Meldet eine inszenierte Ich-Geschichte mit Ehrlich gesagt oder Spoiler ohne echten Erzähler",
        "Streich die Geschichte und nenn die Tatsache.",
    ),
    trigger=(
        r"\b(?:als ich|ich erinnere mich|ehrlich gesagt|spoiler|ich muss zugeben|ich gebe zu|mir ist aufgefallen"
        r"|ich habe festgestellt|meiner erfahrung|ich war überrascht|neulich|ich selbst"
        r"|ich habe (?:\w+ ){0,3}(?:erlebt|gelernt|gesehen|gehört|erfahren))\b"
    ),
)
FALSE_AGENCY = Rule(
    "de_false_agency",
    Wording(
        "German abstraction acts like a person",
        "Flags a German abstract noun making a decision only a person can make, like Die Strategie entschied",
        "Name the person or team who decided.",
    ),
    Wording(
        "Abstraktum handelt wie ein Mensch",
        "Meldet ein Abstraktum, das eine Entscheidung trifft, die nur ein Mensch treffen kann, etwa Die Strategie entschied",
        "Nenn die Person oder das Team, das entschieden hat.",
    ),
    boundary=(
        "Wie humanizer-de Muster 70: Verstoß nur, wenn ein Abstraktum wie Strategie, Kultur, Kennzahl, Technologie, "
        "Markt, Daten, Zahlen oder Politik als Fachgebiet Subjekt eines Verbs ist, das Entscheidung, Absicht oder "
        "Verantwortung voraussetzt, etwa entscheiden, beschließen, erzwingen, wollen, planen, fordern, diktieren. "
        "Sauber sind Institutionen und Gruppen aus Menschen als Handelnde, etwa Regierung, Partei, Gericht, Ministerium, "
        "Unternehmen, Organisation, Verteidigung, ein Land als Staat, die Menschheit. Sauber sind benannte Personen. "
        "Sauber ist fachübliche Metonymie oder echte Funktion, etwa Die Studie zeigt, Das Gesetz verlangt, Das System "
        "speichert die Datei."
    ),
    trigger=(
        r"\b(?:Die|Der|Das)\s+\w*(?:ung|heit|keit|ion|tät|ismus|Daten|Markt|Zahlen|Strategie|Technologie|Politik"
        r"|Wirtschaft)\s+(?:\w+\s+)?(?:entschied|entscheidet|beschloss|beschließt|erzwang|erzwingt|verlangt"
        r"|fordert|zwingt|will|wollte|weiß|wählt|bestimmt|diktiert|treibt|drängt|sucht|hofft|glaubt|versucht"
        r"|möchte|plant|kämpft)\b"
    ),
)
CITATION_MISMATCH = Rule(
    "de_citation_mismatch",
    Wording(
        "German citation that misses the claim",
        "Flags a real German citation placed next to a claim the source does not support",
        "Cite a source that backs the claim, or change the claim.",
    ),
    Wording(
        "Quelle stützt die Aussage nicht",
        "Meldet eine echte Quelle neben einer Aussage, die diese Quelle nicht stützt",
        "Zitier eine Quelle, die die Aussage stützt, oder ändere die Aussage.",
    ),
    trigger=CITATION_CUE,
)
EMPTY_STANDARD_SECTION = Rule(
    "de_empty_standard_section",
    Wording(
        "German empty standard section",
        "Flags a German standard heading followed only by filler that says nothing specific",
        "Merge the section into another one or delete it.",
    ),
    Wording(
        "Standardkapitel ohne Inhalt",
        "Meldet eine Standardüberschrift, unter der nur Fülltext ohne konkrete Aussage steht",
        "Füg den Abschnitt in einen anderen ein oder streich ihn.",
    ),
    trigger=(
        r"\b(?:In diesem (?:Abschnitt|Kapitel|Artikel|Text|Beitrag)|Im Folgenden|Zusammenfassend|Abschließend"
        r"|Fazit|Einleitung|Ausblick)\b"
    ),
)

RULE_SET = RuleSet(
    rules=(
        UNEXPLAINED_FOREIGN_WORD, UNBACKED_SUPERLATIVE, VAGUE_AUTHORITY, FALSE_RANGE, BROKEN_LINK,
        FABRICATED_CITATION, EPISTEMIC_MISCALIBRATION, GAP_FILLING_SPECULATION, INVENTED_ANECDOTE,
        FALSE_AGENCY, CITATION_MISMATCH, EMPTY_STANDARD_SECTION,
    ),
    voted=True,
)
