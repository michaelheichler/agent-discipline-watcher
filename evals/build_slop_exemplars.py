#!/usr/bin/env python3
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict


class ExemplarRow(TypedDict):
    rule: str
    source: str
    text: str


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIRECTORY = Path.home() / ".claude" / "skills" / "stop-slop" / "references"
OUTPUT_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "slop_exemplars.jsonl"
STRUCTURE_SOURCE_NAME = "structures.md"
PHRASE_SOURCE_NAME = "phrases.md"
# WHY: A bracket placeholder embeds as punctuation noise, while a pronoun keeps the phrase shape intact.
PLACEHOLDER_REPLACEMENT = "this"
# WHY: A bare letter carries no meaning for an embedding, so the slot keeps a pronoun instead.
LETTER_PLACEHOLDERS = {"X": "this", "Y": "that", "Z": "it"}
LETTER_PLACEHOLDER_RE = re.compile(r"\b([XYZ])\b")
# WHY: A one or two word exemplar is an exact literal the regex layer already matches, so embedding it only adds a weaker copy.
MIN_EXEMPLAR_WORDS = 3
FILLER_SPLIT_MARKER = "Also cut these filler phrases"
# WHY: The adverb list holds single words the regex layer matches exactly, so only the filler phrases below the split become exemplars.
ADVERB_SECTION = "Adverbs"
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^-\s+(.+?)\s*$")
TABLE_CELL_RE = re.compile(r"^\|\s*(.+?)\s*\|")
PLACEHOLDER_RE = re.compile(r"\[[^]]*\]")
TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")
VARIANT_SEPARATOR = " / "
SKIPPED_CELLS = frozenset({"Pattern", "Avoid", "Fix", "Problem"})
SECTION_RULES = {
    "Binary Contrasts": "binary_contrast",
    "Negative Listing": "negative_listing",
    "Dramatic Fragmentation": "dramatic_fragmentation",
    "Rhetorical Setups": "rhetorical_setup",
    "Formulaic Constructions": "formulaic_construction",
    "False Agency": "false_agency",
    "Narrator-from-a-Distance": "narrator_distance",
    "Passive Voice": "passive_voice",
    "Throat-Clearing Openers": "throat_clearing_opener",
    "Emphasis Crutches": "emphasis_crutch",
    "Business Jargon": "business_jargon",
    "Adverbs": "filler_phrase",
    "Meta-Commentary": "meta_commentary",
    "Performative Emphasis": "performative_emphasis",
    "Telling Instead of Showing": "telling_not_showing",
    "Vague Declaratives": "vague_declarative",
}
# WHY: Rhythm is counted per paragraph and word patterns name a class rather than a phrase, so neither yields an exemplar to embed.
SKIPPED_SECTIONS = {
    "Rhythm Patterns": "counted per paragraph by the rhythm rules",
    "Word Patterns": "names a word class rather than a phrase",
    "Sentence Starters to Avoid": "judges the position of a word, which no embedding measures",
}


def _clean(text: str) -> str:
    stripped = TRAILING_PARENTHETICAL_RE.sub("", text.strip())
    stripped = PLACEHOLDER_RE.sub(PLACEHOLDER_REPLACEMENT, stripped)
    stripped = LETTER_PLACEHOLDER_RE.sub(
        lambda match: LETTER_PLACEHOLDERS[match.group(1)], stripped
    )
    return stripped.strip().strip('"').strip()


def _variants(cell: str) -> Iterator[str]:
    for part in cell.split(VARIANT_SEPARATOR):
        text = _clean(part)
        if len(text.split()) >= MIN_EXEMPLAR_WORDS:
            yield text


def _cell(line: str) -> str | None:
    bullet = BULLET_RE.match(line)
    if bullet:
        return bullet.group(1)
    table = TABLE_CELL_RE.match(line)
    if table and set(table.group(1)) - set("-: "):
        return table.group(1)
    return None


def _rule_for(section: str | None, in_filler: bool) -> str | None:
    if section is None or (section == ADVERB_SECTION and not in_filler):
        return None
    return SECTION_RULES.get(section)


def _rows(source_name: str, text: str) -> Iterator[ExemplarRow]:
    section: str | None = None
    in_filler = False
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            section, in_filler = heading.group(1), False
            continue
        in_filler = in_filler or FILLER_SPLIT_MARKER in line
        rule = _rule_for(section, in_filler)
        cell = _cell(line) if rule else None
        if cell is None or cell.strip('*') in SKIPPED_CELLS:
            continue
        for variant in _variants(cell):
            yield ExemplarRow(rule=rule, source=source_name, text=variant)


def _deduplicated(rows: Iterator[ExemplarRow]) -> list[ExemplarRow]:
    seen: set[tuple[str, str]] = set()
    kept: list[ExemplarRow] = []
    for row in rows:
        key = (row["rule"], row["text"].lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def build() -> list[ExemplarRow]:
    rows: list[ExemplarRow] = []
    for source_name in (STRUCTURE_SOURCE_NAME, PHRASE_SOURCE_NAME):
        text = (SKILL_DIRECTORY / source_name).read_text(encoding="utf-8")
        rows.extend(_rows(source_name, text))
    return _deduplicated(iter(rows))


def main() -> None:
    rows = build()
    missing = set(SECTION_RULES.values()) - {row["rule"] for row in rows}
    if missing:
        raise SystemExit(f"no exemplar produced for rules: {sorted(missing)}")
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    OUTPUT_PATH.write_text(payload, encoding="utf-8")
    print(f"{len(rows)} exemplars written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
