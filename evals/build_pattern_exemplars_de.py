#!/usr/bin/env python3
"""Draw the German clean exemplars by seed, because a hand-picked side would carry the picker's taste into the vote."""
import hashlib
import importlib
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

from ai_corpus_de import AI_CORPUS_PATH, LABELS_PATH, AiRow, ai_corpus_digest, load_ai_corpus, load_labels

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_sentences_de.jsonl"
CORPUS_MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_human_manifest_de.json"
JUDGE_STAGE_PATH = REPOSITORY_ROOT / "evals" / "judge_stage_de.json"
OUTPUT_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "pattern_exemplars_de.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "pattern_exemplars_de.json"
SEED = 20261001
CLEAN_PER_GENRE = 1
CLEAN_PER_RULE = 4
ASSISTANT_CLEAN_PER_RULE = 2
GENRES = ("encyclopedia", "literature")
MAX_CHARS = 220
CLEAN = "clean"
VIOLATING = "violating"
VIOLATING_PER_RULE = 4
LABELER = "claude-opus-5-5, by hand against the catalog definitions, 2026-10-01"
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


def usable_text(text: str) -> bool:
    """Shared with the violating draw, because a side that admits markup the other side refuses lets markup cast the vote."""
    return len(text) <= MAX_CHARS and _balanced(text) and not any(
        pattern.search(text) for pattern in (MARKUP_RESIDUE_RE, SPLIT_FRAGMENT_RE, FRONT_MATTER_RE)
    )


def _usable(rule: str, row: CorpusRow) -> bool:
    """Skip obvious triggers, because a human sentence can still instantiate the pattern it should stand against."""
    if not usable_text(row.text):
        return False
    trigger = TRIGGERS.get(rule)
    return trigger is None or trigger.search(row.text) is None


class Pool(NamedTuple):
    """Share one shuffle across all rules, because a sentence drawn for one rule must not stand clean for another."""

    order: list[CorpusRow]
    used: set[int]


def _draw(pool: Pool, rule: str, genre: str, count: int = CLEAN_PER_GENRE) -> list[CorpusRow]:
    found: list[CorpusRow] = []
    for row in pool.order:
        if len(found) == count:
            return found
        if row.genre == genre and row.row not in pool.used and _usable(rule, row):
            found.append(row)
            pool.used.add(row.row)
    if len(found) == count:
        return found
    raise ValueError(f"{rule}: the corpus holds fewer than {count} usable {genre} sentences")


def _exemplar(rule: str, row: CorpusRow) -> dict:
    return {
        "rule": rule, "label": CLEAN, "origin": f"human/{row.genre}", "source": row.source,
        "document": row.document, "row": row.row, "text": row.text,
    }


def build(corpus: list[CorpusRow], per_genre: Mapping[str, int], seed: int = SEED) -> list[dict]:
    """Half from each genre, because a side drawn from one genre would let the genre stand in for the pattern."""
    order = list(corpus)
    random.Random(seed).shuffle(order)
    pool = Pool(order, set())
    return [
        _exemplar(rule, row)
        for rule, count in per_genre.items() for genre in GENRES for row in _draw(pool, rule, genre, count)
    ]


def _assistant_exemplar(rule: str, row: AiRow, label: str) -> dict:
    return {
        "rule": rule, "label": label, "origin": f"assistant/{row.source}", "source": row.source,
        "model": row.model, "document": row.document, "row": row.line, "text": row.text,
    }


def assistant_clean_side(labels: list[dict], corpus: list[AiRow], rules: Iterable[str], seed: int = SEED) -> list[dict]:
    """Labeled near misses from the violating side's own models, because a human-only clean side let source stand in for the pattern."""
    by_line = {row.line: row for row in corpus}
    chosen: list[dict] = []
    for rule in rules:
        lines = [label["line"] for label in labels if label["rule"] == rule and label["label"] == CLEAN]
        if len(lines) < ASSISTANT_CLEAN_PER_RULE:
            continue
        random.Random(f"{seed}:{rule}:clean").shuffle(lines)
        chosen.extend(_assistant_exemplar(rule, by_line[line], CLEAN) for line in lines[:ASSISTANT_CLEAN_PER_RULE])
    return chosen


def human_per_genre(assistant_clean: list[dict], rules: Iterable[str]) -> dict[str, int]:
    """Human rows fill the gap, because a rule with no labeled near miss still needs four clean neighbours."""
    have = Counter(row["rule"] for row in assistant_clean)
    return {rule: (CLEAN_PER_RULE - have[rule]) // len(GENRES) for rule in rules}


def violating_side(labels: list[dict], corpus: list[AiRow], rules: Iterable[str]) -> tuple[list[dict], dict[str, int]]:
    """First four in label order, because the labels follow the seeded candidate order and any later pick is a hand pick."""
    by_line = {row.line: row for row in corpus}
    chosen: list[dict] = []
    short: dict[str, int] = {}
    for rule in rules:
        lines = [label["line"] for label in labels if label["rule"] == rule and label["label"] == VIOLATING]
        if len(lines) < VIOLATING_PER_RULE:
            short[rule] = len(lines)
            continue
        chosen.extend(_assistant_exemplar(rule, by_line[line], VIOLATING) for line in lines[:VIOLATING_PER_RULE])
    return chosen, short


def merged(violating: list[dict], clean: list[dict], rules: Iterable[str]) -> list[dict]:
    """Grouped by rule, because the judge prompt reads each rule's two sides together."""
    return [row for rule in rules for row in violating + clean if row["rule"] == rule]


def serialize(exemplars: list[dict]) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "".join(encoder.encode(row) + "\n" for row in exemplars)


def _precisions() -> dict[str, float]:
    if not JUDGE_STAGE_PATH.is_file():
        return {}
    measured = json.loads(JUDGE_STAGE_PATH.read_text(encoding="utf-8"))
    return {rule: row["after_judge"]["precision"] for rule, row in measured.items()}


class Digests(NamedTuple):
    exemplars: str
    corpus: str
    ai_corpus: str
    labels: str


def _rule_entry(rule: str, exemplars: list[dict], precisions: dict[str, float]) -> dict[str, object]:
    mine = [row for row in exemplars if row["rule"] == rule]
    clean_origins = Counter(row["origin"].split("/")[0] for row in mine if row["label"] == CLEAN)
    return {
        "catalog_row": CATALOG_ROWS[rule], "judge_precision": precisions.get(rule),
        "violating": sum(1 for row in mine if row["label"] == VIOLATING), "clean_origins": dict(sorted(clean_origins.items())),
    }


def build_manifest(exemplars: list[dict], digests: Digests, short: dict[str, int]) -> dict[str, object]:
    precisions = _precisions()
    rules = list(dict.fromkeys(row["rule"] for row in exemplars))
    return {
        "exemplars": OUTPUT_PATH.name,
        "sha256": digests.exemplars,
        "corpus": CORPUS_PATH.name,
        "corpus_sha256": digests.corpus,
        "ai_corpus": AI_CORPUS_PATH.name,
        "ai_corpus_sha256": digests.ai_corpus,
        "labels": LABELS_PATH.name,
        "labels_sha256": digests.labels,
        "labeler": LABELER,
        "seed": SEED,
        "clean_per_rule": CLEAN_PER_RULE,
        "assistant_clean_per_rule": ASSISTANT_CLEAN_PER_RULE,
        "violating_per_rule": VIOLATING_PER_RULE,
        "rules": {rule: _rule_entry(rule, exemplars, precisions) for rule in rules},
        "silent_rules": {rule: f"{count} violating sentences labeled" for rule, count in short.items()},
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
    ai_sha = ai_corpus_digest()
    rules = registered_rules()
    labels, ai_rows = load_labels(), load_ai_corpus()
    violating, short = violating_side(labels, ai_rows, rules)
    assistant_clean = assistant_clean_side(labels, ai_rows, rules)
    clean = assistant_clean + build(load_corpus(), human_per_genre(assistant_clean, rules))
    exemplars = merged(violating, clean, rules)
    serialized = serialize(exemplars)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    OUTPUT_PATH.write_text(serialized, encoding="utf-8", newline="\n")
    labels_sha = hashlib.sha256(LABELS_PATH.read_bytes()).hexdigest()
    manifest = build_manifest(exemplars, Digests(digest, corpus_sha, ai_sha, labels_sha), short)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(exemplars)} exemplars over {len(manifest['rules'])} rules, {len(short)} rules without a violating side")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
