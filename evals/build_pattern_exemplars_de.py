#!/usr/bin/env python3
"""Draw the German clean exemplars by seed, because a hand-picked side would carry the picker's taste into the vote."""
import hashlib
import importlib
import json
import random
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_sentences_de.jsonl"
CORPUS_MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_manifest_de.json"
JUDGE_STAGE_PATH = REPOSITORY_ROOT / "evals" / "judge_stage_de.json"
OUTPUT_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "pattern_exemplars_de.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "pattern_exemplars_de.json"
SEED = 20261001
CLEAN_PER_GENRE = 2
GENRES = ("encyclopedia", "literature")
MAX_CHARS = 220
CLEAN = "clean"
MARKUP_RESIDUE_RE = re.compile(r"[|{}\[\]=<>*#_\r\n]|\s{2,}|https?://")
SPLIT_FRAGMENT_RE = re.compile(
    r"(?:\b[A-ZÄÖÜ]|\b[IVXLC]+|\b(?:sel|bzw|usw|vgl|ca|St|Dr|Nr|z|Amtl|Hrsg))\.$"
    r"|^(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\b"
)
FRONT_MATTER_RE = re.compile(r"Transkription|Umschlagbild|Gutenberg|Verfasser behält|Gemeingut")
CATALOG_ROWS: Mapping[str, int] = {
    "de_passive_voice": 6,
    "de_stock_phrase": 8,
    "de_unexplained_foreign_word": 12,
    "de_unbacked_superlative": 15,
    "de_dichotomy_template": 25,
    "de_shallow_participle": 27,
    "de_vague_authority": 28,
    "de_false_range": 29,
    "de_synonym_rotation": 31,
    "de_fake_analysis_tail": 33,
    "de_comparative_framing": 34,
    "de_register_collapse": 38,
    "de_broken_link": 47,
    "de_fabricated_citation": 48,
    "de_style_shift": 52,
    "de_fragment_heading": 56,
    "de_rhetorical_question": 57,
    "de_markerless_closer": 62,
    "de_retroactive_nuance": 64,
    "de_epistemic_miscalibration": 66,
    "de_gap_filling_speculation": 67,
    "de_invented_anecdote": 68,
    "de_false_agency": 69,
    "de_citation_mismatch": 71,
    "de_empty_standard_section": 73,
}
CITATION_RE = re.compile(r"\b(?:ISBN|DOI|S\.\s*\d|Hrsg)\b|\(\d{4}\)")
TRIGGERS: Mapping[str, re.Pattern[str]] = {
    "de_passive_voice": re.compile(r"\b(?:werden|wird|wirst|wurde|wurden|worden|geworden)\b", re.IGNORECASE),
    "de_unbacked_superlative": re.compile(
        r"\b(?:(?:am|der|die|das|den|dem|des)\s+\w+(?:st|ßt)e[nmrs]?|\w*(?:beste|einzige|immer|niemals)\w*)\b", re.IGNORECASE,
    ),
    "de_dichotomy_template": re.compile(r"\btrotz\b", re.IGNORECASE),
    "de_shallow_participle": re.compile(r",\s*\w+end\b"),
    "de_vague_authority": re.compile(r"\b(?:manche|einige|viele|Experten|Studien|Berichte)\b", re.IGNORECASE),
    "de_false_range": re.compile(r"\bvon\s+\w+\s+bis\b", re.IGNORECASE),
    "de_fake_analysis_tail": re.compile(r",\s*was\b"),
    "de_comparative_framing": re.compile(r"\b(?:weniger|vielmehr)\b", re.IGNORECASE),
    "de_register_collapse": re.compile(r"\b(?:halt|eben|mal|ja|doch|eh|echt)\b", re.IGNORECASE),
    "de_broken_link": CITATION_RE,
    "de_fabricated_citation": CITATION_RE,
    "de_citation_mismatch": CITATION_RE,
    "de_rhetorical_question": re.compile(r"\?"),
    "de_retroactive_nuance": re.compile(r"\b(?:genauer|fairerweise|eigentlich)\b", re.IGNORECASE),
    "de_epistemic_miscalibration": re.compile(r"\b(?:scheint|möglicherweise|grundlegend|entscheidend)\b", re.IGNORECASE),
    "de_gap_filling_speculation": re.compile(r"\b(?:vermutlich|wahrscheinlich|wohl|angeblich|möglicherweise)\b", re.IGNORECASE),
    "de_invented_anecdote": re.compile(r"\b(?:ich|mich|mir|mein\w*)\b", re.IGNORECASE),
}


class CorpusRow(NamedTuple):
    row: int
    genre: str
    source: str
    document: int
    text: str


def load_corpus(path: Path = CORPUS_PATH) -> list[CorpusRow]:
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    return [
        CorpusRow(number, row["genre"], row["source"], row["document"], row["text"])
        for number, row in enumerate(rows, 1)
    ]


def corpus_digest(path: Path = CORPUS_PATH) -> str:
    """Checked against the corpus manifest, because a drifted corpus would change every draw under the same seed."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))["sha256"]
    if digest != expected:
        raise ValueError(f"{path.name} hashes to {digest}, the corpus manifest records {expected}; rebuild the corpus")
    return digest


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")") and text.count("„") == text.count("“")


def _usable(rule: str, row: CorpusRow) -> bool:
    """Skip obvious triggers, because a human sentence can still instantiate the pattern it should stand against."""
    if len(row.text) > MAX_CHARS or not _balanced(row.text) or any(
        pattern.search(row.text) for pattern in (MARKUP_RESIDUE_RE, SPLIT_FRAGMENT_RE, FRONT_MATTER_RE)
    ):
        return False
    trigger = TRIGGERS.get(rule)
    return trigger is None or trigger.search(row.text) is None


class Pool(NamedTuple):
    """Share one shuffle across all rules, because a sentence drawn for one rule must not stand clean for another."""

    order: list[CorpusRow]
    used: set[int]


def _draw(pool: Pool, rule: str, genre: str) -> list[CorpusRow]:
    found: list[CorpusRow] = []
    for row in pool.order:
        if row.genre == genre and row.row not in pool.used and _usable(rule, row):
            found.append(row)
            pool.used.add(row.row)
        if len(found) == CLEAN_PER_GENRE:
            return found
    raise ValueError(f"{rule}: the corpus holds fewer than {CLEAN_PER_GENRE} usable {genre} sentences")


def _exemplar(rule: str, row: CorpusRow) -> dict:
    return {
        "rule": rule, "label": CLEAN, "origin": f"human/{row.genre}", "source": row.source,
        "document": row.document, "row": row.row, "text": row.text,
    }


def build(corpus: list[CorpusRow], rules: Iterable[str], seed: int = SEED) -> list[dict]:
    """Half from each genre, because a side drawn from one genre would let the genre stand in for the pattern."""
    order = list(corpus)
    random.Random(seed).shuffle(order)
    pool = Pool(order, set())
    return [_exemplar(rule, row) for rule in rules for genre in GENRES for row in _draw(pool, rule, genre)]


def serialize(exemplars: list[dict]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row) + "\n" for row in exemplars)


def _precisions() -> dict[str, float]:
    if not JUDGE_STAGE_PATH.is_file():
        return {}
    measured = json.loads(JUDGE_STAGE_PATH.read_text(encoding="utf-8"))
    return {rule: row["after_judge"]["precision"] for rule, row in measured.items()}


def build_manifest(exemplars: list[dict], digests: tuple[str, str]) -> dict[str, object]:
    precisions = _precisions()
    rules = list(dict.fromkeys(row["rule"] for row in exemplars))
    return {
        "exemplars": OUTPUT_PATH.name,
        "sha256": digests[0],
        "corpus": CORPUS_PATH.name,
        "corpus_sha256": digests[1],
        "seed": SEED,
        "clean_per_rule": CLEAN_PER_GENRE * len(GENRES),
        "rules": {
            rule: {"catalog_row": CATALOG_ROWS[rule], "judge_precision": precisions.get(rule)} for rule in rules
        },
    }


def registered_rules() -> tuple[str, ...]:
    """Fail on drift, because a rule missing here would ship without a clean side."""
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    names = tuple(rule.name for rule in importlib.import_module("lib.german_rules").voted())
    if set(names) != set(CATALOG_ROWS):
        raise ValueError(f"registry and catalog map differ: {sorted(set(names) ^ set(CATALOG_ROWS))}")
    return tuple(sorted(names, key=CATALOG_ROWS.__getitem__))


def main() -> None:
    corpus_sha = corpus_digest()
    exemplars = build(load_corpus(), registered_rules())
    serialized = serialize(exemplars)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    manifest = build_manifest(exemplars, (digest, corpus_sha))
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(exemplars)} clean exemplars over {len(manifest['rules'])} rules")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
