#!/usr/bin/env python3
"""Wiktionary's Worttrennung field is citable and free, because that beats hand-guessing a syllable truth set."""
import argparse
import datetime
import importlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
german_syllables = importlib.import_module("lib.german_syllables")

API_URL = "https://de.wiktionary.org/w/api.php"
USER_AGENT = "agent-discipline-watcher-eval/0.1 (research script, no bot account)"
SOURCE_URL = "https://de.wiktionary.org (Worttrennung field via the public action API)"
SOURCE_LICENSE = "CC BY-SA 3.0 and GFDL, per de.wiktionary.org/wiki/Wiktionary:Impressum"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "syllable_counter.json"
BATCH_SIZE = 50
BATCH_DELAY_SECONDS = 1.0
WORTTRENNUNG_RE = re.compile(r"\{\{Worttrennung\}\}\s*\n:\s*(.+)")

WORDS = (
    "Haus", "Maus", "Baum", "Zeit", "Heute", "Freund", "Freude", "Auge", "Auto", "Europa",
    "Häuser", "Bäume", "Söhne", "Qualität", "Quelle", "Quadrat", "Quittung", "Beispiel",
    "Theater", "Idee", "Schuh", "Freundschaft", "Wasser", "Sonne", "Mond", "Blume", "Tisch",
    "Stuhl", "Fenster", "Buch", "Zeitung", "Computer", "Telefon", "Fahrrad", "Flugzeug",
    "Straße", "Brücke", "Berg", "Wald", "Garten", "Stadt", "Dorf", "Meer", "Fluss", "Regen",
    "Schnee", "Wind", "Himmel", "Erde", "Stern", "Freiheit", "Liebe", "Hoffnung", "Glück",
    "Arbeit", "Leben", "Familie", "Lehrer", "Schüler", "Arzt", "Krankenhaus", "Universität",
    "Bibliothek", "Museum", "Kirche", "Rathaus", "Bahnhof", "Flughafen", "Restaurant",
    "Krankenversicherung", "Rechtsschutzversicherung", "Geschwindigkeitsbegrenzung",
    "Bundesverfassungsgericht", "Arbeitslosenversicherung", "Gesundheitsministerium",
    "Lebensversicherung", "Umweltverschmutzung", "Yoga", "System", "Symbol",
)


def batches(words: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [words[start:start + BATCH_SIZE] for start in range(0, len(words), BATCH_SIZE)]


def fetch_batch(titles: tuple[str, ...]) -> dict:
    query = urllib.parse.urlencode({
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "titles": "|".join(titles),
    })
    request = urllib.request.Request(API_URL + "?" + query, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def wikitext_by_title(payload: dict) -> dict[str, str]:
    pages = payload.get("query", {}).get("pages", {})
    resolved = {}
    for page in pages.values():
        title = page.get("title")
        revisions = page.get("revisions")
        if title and revisions:
            resolved[title] = revisions[0]["slots"]["main"]["*"]
    return resolved


def reference_syllables(wikitext: str) -> int | None:
    """A Pl. tag can trail the first form with no comma, because then only the first token is the singular."""
    match = WORTTRENNUNG_RE.search(wikitext)
    if not match:
        return None
    tokens = match.group(1).split()
    if not tokens:
        return None
    first_form = tokens[0].rstrip(",")
    if not first_form or "{{" in first_form:
        return None
    return first_form.count("\u00b7") + 1


def _compare_batch(batch: tuple[str, ...], mismatches: list[dict], skipped: list[str]) -> int:
    texts = wikitext_by_title(fetch_batch(batch))
    resolved = 0
    for word in batch:
        wikitext = texts.get(word)
        reference = reference_syllables(wikitext) if wikitext else None
        if reference is None:
            skipped.append(word)
            continue
        resolved += 1
        computed = german_syllables.count_syllables(word)
        if computed != reference:
            mismatches.append({"word": word, "reference": reference, "computed": computed})
    return resolved


def collect_results(words: tuple[str, ...]) -> tuple[list[dict], list[str], int]:
    mismatches: list[dict] = []
    skipped: list[str] = []
    resolved_total = 0
    word_batches = batches(words)
    for batch_index, batch in enumerate(word_batches):
        resolved_total += _compare_batch(batch, mismatches, skipped)
        if batch_index + 1 < len(word_batches):
            time.sleep(BATCH_DELAY_SECONDS)
    return mismatches, skipped, resolved_total


def build_report(words: tuple[str, ...]) -> dict:
    mismatches, skipped, resolved_total = collect_results(words)
    error_rate = round(len(mismatches) / resolved_total, 4) if resolved_total else None
    return {
        "source": SOURCE_URL,
        "license": SOURCE_LICENSE,
        "retrieved": datetime.date.today().isoformat(),
        "n_words_requested": len(words),
        "n_resolved": resolved_total,
        "n_skipped": len(skipped),
        "skipped_words": sorted(skipped),
        "n_mismatches": len(mismatches),
        "error_rate": error_rate,
        "mismatches": sorted(mismatches, key=lambda row: row["word"]),
    }


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure german_syllables.count_syllables against Wiktionary Worttrennung hyphenation."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    parsed = _arguments(sys.argv[1:] if argv is None else argv)
    report = build_report(WORDS)
    parsed.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
