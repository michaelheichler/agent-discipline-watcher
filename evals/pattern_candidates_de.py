#!/usr/bin/env python3
"""Order German AI sentences by seed for labeling, because the violating side must come from a draw anyone can repeat."""
import argparse
import random
import re
from collections.abc import Mapping

from ai_corpus_de import AiRow, ai_corpus_digest, load_ai_corpus, load_labels
from build_pattern_exemplars_de import SEED, usable_text

MIN_WORDS = 4
BATCH = 16
CITATION_CUE = r"\b(?:ISBN|DOI|et al|Journal|Zeitschrift|veröffentlicht|laut (?:einer|der|dem) (?:Studie|Bericht|Umfrage))\b|\(\d{4}\)"
CANDIDATE_PATTERNS: Mapping[str, re.Pattern[str]] = {
    rule: re.compile(pattern, re.IGNORECASE)
    for rule, pattern in {
        "de_passive_voice": r"\b(?:wird|werden|wurde|wurden|worden)\b",
        "de_stock_phrase": (
            r"\b(?:nach wie vor|unter die Lupe|im Fokus|Hand in Hand|auf Augenhöhe|in aller Munde|ins Leben gerufen"
            r"|unter Beweis|an Bedeutung gewinn\w*|den Grundstein|Meilenstein|Dreh- und Angelpunkt|Schritt halten"
            r"|Weichen|auf der Hand|an einem Strang|nicht zuletzt|in den Startlöchern|auf Hochtouren|im Mittelpunkt"
            r"|ein Zeichen|den Weg|eine Lanze|im Endeffekt|diesbezüglich|nichtsdestotrotz|in der heutigen)\b"
        ),
        "de_unexplained_foreign_word": (
            r"\b(?:Tools?|Features?|Workflow|Insights?|Mindset|Skills|Content|Commitment|Challenge|Performance"
            r"|Deadline|Feedback|Use Case|Stakeholder|Benefits?|Lifestyle|Highlights?|Community|Influencer"
            r"|Branding|Engagement|Impact|Framework|Roadmap|Comeback|Lockdown|Statement|Hype|Release)\b"
        ),
        "de_unbacked_superlative": (
            r"\b(?:(?:am|der|die|das|den|dem|des)\s+\w+(?:st|ßt)e[nmrs]?|\w*(?:beste|einzige|immer|niemals)\w*)\b"
        ),
        "de_dichotomy_template": r"\btrotz\b|Herausforderung",
        "de_shallow_participle": r",\s*(?:\w+\s+){0,3}(?!während\b)\w+end\b[.,]?\s*$|,\s*\w+end\b,",
        "de_vague_authority": (
            r"\b(?:Experten|Studien|Berichte|Kritiker|Manche|Einige|viele Menschen|Beobachter|Analysten|Fachleute"
            r"|es heißt)\b"
        ),
        "de_false_range": r"\bvon\b[^,.]{1,40}\bbis\b",
        "de_synonym_rotation": (
            r"\b(?:die|der|das)\s+(?:\w+-)?(?:Metropole|Hansestadt|Hauptstadt|Konzern|Riese|Gigant|Hersteller"
            r"|Sängerin|Sänger|Schauspieler\w*|Musiker\w*|Künstler\w*|Politiker\w*|Verein|Klub|Club|Mannschaft|Elf)\b"
        ),
        "de_fake_analysis_tail": r",\s*(?:was|wodurch|womit)\b",
        "de_comparative_framing": r"\b(?:vielmehr|nicht so sehr|weniger\b[^.]{1,40}\bals)\b",
        "de_register_collapse": r"\b(?:halt|mal|eh|echt|krass|total|super|cool|okay)\b|\w\s+(?:ja|doch|eben)\b",
        "de_broken_link": r"https?://|www\.",
        "de_fabricated_citation": CITATION_CUE,
        "de_rhetorical_question": r"\?$",
        "de_markerless_closer": (
            r"\b(?:insgesamt|zeigt|bleibt|wichtig\w*|Bedeutung|beeindruckend\w*|spannend\w*|Zukunft|deutlich)\b"
        ),
        "de_retroactive_nuance": (
            r"\b(?:genauer|fairerweise|eigentlich|streng genommen|genau genommen|besser gesagt|anders gesagt"
            r"|mit anderen Worten)\b"
        ),
        "de_epistemic_miscalibration": (
            r"\b(?:grundlegend|entscheidend|zweifellos|unbestreitbar|enorm|revolution\w*|bahnbrechend|scheint"
            r"|möglicherweise|vielleicht|eventuell)\b"
        ),
        "de_gap_filling_speculation": (
            r"\b(?:vermutlich|wahrscheinlich|wohl|angeblich|offenbar|unklar|spekuliert|Gerüchte?|bedeckt)\b"
        ),
        "de_invented_anecdote": (
            r"\b(?:als ich|ich erinnere mich|ehrlich gesagt|spoiler|ich muss zugeben|ich gebe zu|mir ist aufgefallen"
            r"|ich habe festgestellt|meiner erfahrung|ich war überrascht|neulich|ich selbst"
            r"|ich habe (?:\w+ ){0,3}(?:erlebt|gelernt|gesehen|gehört|erfahren))\b"
        ),
        "de_false_agency": (
            r"\b(?:Die|Der|Das)\s+\w*(?:ung|heit|keit|ion|tät|ismus|Daten|Markt|Zahlen|Strategie|Technologie|Politik"
            r"|Wirtschaft)\s+(?:\w+\s+)?(?:entschied|entscheidet|beschloss|beschließt|erzwang|erzwingt|verlangt"
            r"|fordert|zwingt|will|wollte|weiß|wählt|bestimmt|diktiert|treibt|drängt|sucht|hofft|glaubt|versucht"
            r"|möchte|plant|kämpft)\b"
        ),
        "de_citation_mismatch": CITATION_CUE,
        "de_empty_standard_section": (
            r"\b(?:In diesem (?:Abschnitt|Kapitel|Artikel|Text|Beitrag)|Im Folgenden|Zusammenfassend|Abschließend"
            r"|Fazit|Einleitung|Ausblick)\b"
        ),
    }.items()
}


def candidates(rule: str, corpus: list[AiRow], seed: int = SEED) -> list[AiRow]:
    """Seeded per rule, because the labels cover a prefix of this order and any other order would orphan them."""
    pattern = CANDIDATE_PATTERNS.get(rule)
    if pattern is None:
        return []
    found = [
        row for row in corpus
        if len(row.text.split()) >= MIN_WORDS and usable_text(row.text) and pattern.search(row.text)
    ]
    random.Random(f"{seed}:{rule}").shuffle(found)
    return found


def _neighbour(corpus: list[AiRow], row: AiRow, step: int) -> str:
    index = row.line - 1 + step
    if 0 <= index < len(corpus) and corpus[index].document == row.document and corpus[index].source == row.source:
        return corpus[index].text
    return ""


def off_prefix_rules(labels: list[dict], corpus: list[AiRow], seed: int = SEED) -> list[str]:
    """Strict prefix, because a skipped candidate is a hand pick and the seed exists to stop hand picks."""
    drifted = []
    for rule in dict.fromkeys(row["rule"] for row in labels):
        labeled = [row["line"] for row in labels if row["rule"] == rule]
        drawn = [row.line for row in candidates(rule, corpus, seed)[: len(labeled)]]
        if labeled != drawn:
            drifted.append(rule)
    return drifted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rule", choices=sorted(CANDIDATE_PATTERNS))
    parser.add_argument("--count", type=int, default=BATCH)
    arguments = parser.parse_args()
    ai_corpus_digest()
    corpus = load_ai_corpus()
    labels = load_labels()
    drifted = off_prefix_rules(labels, corpus)
    if drifted:
        raise SystemExit(f"labels leave the seeded candidate order for {drifted}")
    found = candidates(arguments.rule, corpus)
    start = sum(1 for row in labels if row["rule"] == arguments.rule)
    print(f"{arguments.rule}: {len(found)} candidates, {start} labeled")
    for row in found[start : start + arguments.count]:
        print(f"[{row.line}] {row.source} doc {row.document}")
        print(f"  < {_neighbour(corpus, row, -1)}")
        print(f"  = {row.text}")
        print(f"  > {_neighbour(corpus, row, 1)}")


if __name__ == "__main__":
    main()
