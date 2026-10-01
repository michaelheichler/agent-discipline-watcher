#!/usr/bin/env python3
"""Score every German rule that fires without a model through scan_all, because routing decides which German rule ever sees a line."""
import importlib
import json
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALS = REPOSITORY_ROOT / "evals"
HOOKS = str(REPOSITORY_ROOT / "hooks")
OUTPUT_PATH = EVALS / "german_hit_rate.json"
HITS_PATH = EVALS / "german_static_hits.jsonl"
SAMPLE_NAME = "sample.md"
GERMAN = "de"
PER = 1000
PUNCTUATION_RULES = ("quote_marks", "genitive_apostrophe", "typed_ellipsis", "banned_dash", "spaced_hyphen")
DOCUMENT_RULES = (
    "de_sentence_length", "de_uniform_rhythm", "de_uniform_paragraphs",
    "de_repeated_connector", "de_long_compound", "dash_cluster",
)


def hook_module(name: str) -> ModuleType:
    """Import on demand, because a module-level path change would run on every import of this script."""
    if HOOKS not in sys.path:
        sys.path.insert(0, HOOKS)
    return importlib.import_module("lib." + name)


class Corpus(NamedTuple):
    name: str
    path: Path
    manifest: Path


SENTENCE_CORPORA = (
    Corpus("human_sentences", EVALS / "corpus_human_sentences_de.jsonl", EVALS / "corpus_human_manifest_de.json"),
    Corpus("ai_sentences", EVALS / "corpus_ai_sentences_de.jsonl", EVALS / "corpus_ai_manifest_de.json"),
)
PARAGRAPH_CORPUS = Corpus("paragraphs", EVALS / "corpus_paragraphs_de.jsonl", EVALS / "corpus_paragraph_manifest_de.json")


class Unit(NamedTuple):
    corpus: str
    line: int
    side: str
    genre: str
    text: str


def static_registry_rules() -> tuple[str, ...]:
    """Skip the voted modules, because a SEMANTIC rule finds nothing until the embedding vote and the judge run."""
    rule_sets = hook_module("german_rules").RULE_SETS
    return tuple(rule.name for rule_set in rule_sets if not rule_set.voted for rule in rule_set.rules)


def measured_rules() -> tuple[str, ...]:
    return static_registry_rules() + PUNCTUATION_RULES + DOCUMENT_RULES


def _rows(path: Path) -> Iterator[tuple[int, dict]]:
    with path.open(encoding="utf-8") as stream:
        lines = list(stream)
    return ((number, json.loads(line)) for number, line in enumerate(lines, 1) if line.strip())


def sentence_units(corpus: Corpus) -> Iterator[Unit]:
    for number, row in _rows(corpus.path):
        if "genre" in row:
            yield Unit(corpus.name, number, "human", row["genre"], row["text"])
        else:
            yield Unit(corpus.name, number, "ai", row["source"], row["text"])


def paragraph_units(corpus: Corpus) -> Iterator[Unit]:
    for number, row in _rows(corpus.path):
        side = "human" if row["origin"] == "human" else "ai"
        genre = row["genre"] if side == "human" else "wildchat"
        yield Unit(corpus.name, number, side, genre, "\n\n".join(row["paragraphs"]))


def german_hits(text: str, rules: frozenset[str], config: dict) -> dict[str, dict]:
    """Keep the first finding per rule, because the rate counts units that fire, not findings."""
    first: dict[str, dict] = {}
    for finding in hook_module("scanner").scan_all(SAMPLE_NAME, text, config):
        if finding["rule"] in rules and finding.get("language") == GERMAN:
            first.setdefault(finding["rule"], {"finding_line": finding["line"], "match": finding.get("match"),
                                               "snippet": finding.get("snippet")})
    return first


def routed_german(text: str) -> bool:
    """Mirror the scanner's routing on an empty verdict cache, because a short sentence falls back to English."""
    paragraphs = hook_module("prose_language").paragraph_languages(text)
    return any(paragraph.language == GERMAN for paragraph in paragraphs)


class Tally(NamedTuple):
    units: Counter
    routed: Counter
    hits: dict[str, Counter]
    rows: list[dict]


def tally(units: Iterable[Unit], rules: frozenset[str], config: dict) -> Tally:
    counted = Tally(Counter(), Counter(), {rule: Counter() for rule in sorted(rules)}, [])
    for unit in units:
        key = unit.side + "/" + unit.genre
        counted.units[key] += 1
        counted.routed[key] += routed_german(unit.text)
        for rule, hit in german_hits(unit.text, rules, config).items():
            counted.hits[rule][key] += 1
            counted.rows.append({"rule": rule, "corpus": unit.corpus, "line": unit.line,
                                 "side": unit.side, "genre": unit.genre, **hit})
    return counted


def _per_thousand(hits: int, units: int) -> float | None:
    return round(PER * hits / units, 3) if units else None


def _side_record(counts: Counter, units: Counter, side: str) -> dict[str, object]:
    keys = sorted(key for key in units if key.startswith(side + "/"))
    hits, total = sum(counts[key] for key in keys), sum(units[key] for key in keys)
    return {
        "hits": hits, "per_1000": _per_thousand(hits, total),
        "by_genre": {key.split("/", 1)[1]: {"hits": counts[key], "per_1000": _per_thousand(counts[key], units[key])}
                     for key in keys},
    }


def _corpus_record(counted: Tally, rule: str) -> dict[str, object]:
    return {side: _side_record(counted.hits[rule], counted.units, side) for side in ("human", "ai")}


def _gate(rule: str) -> str:
    return hook_module("config").DEFAULTS["rule_gates"].get(rule, "family_default")


def _manifest_hash(corpus: Corpus) -> str:
    return json.loads(corpus.manifest.read_text(encoding="utf-8"))["sha256"]


def build_report(sentences: Tally, paragraphs: Tally) -> dict[str, object]:
    rules = {
        rule: {"gate": _gate(rule), "scope": "document" if rule in DOCUMENT_RULES else "sentence",
               "sentences": _corpus_record(sentences, rule), "paragraphs": _corpus_record(paragraphs, rule)}
        for rule in measured_rules()
    }
    return {
        "corpora": {corpus.path.name: _manifest_hash(corpus) for corpus in (*SENTENCE_CORPORA, PARAGRAPH_CORPUS)},
        "path": SAMPLE_NAME,
        "units": {"sentences": dict(sentences.units), "paragraphs": dict(paragraphs.units)},
        "routed_german": {"sentences": dict(sentences.routed), "paragraphs": dict(paragraphs.routed)},
        "rules": rules,
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
    path.write_text("".join(encoder.encode(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


def main() -> None:
    rules = frozenset(measured_rules())
    with tempfile.TemporaryDirectory() as state:
        config = {"state_root": str(Path(state) / "state")}
        units = (unit for corpus in SENTENCE_CORPORA for unit in sentence_units(corpus))
        sentences = tally(units, rules, config)
        paragraphs = tally(paragraph_units(PARAGRAPH_CORPUS), rules, config)
    report = build_report(sentences, paragraphs)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    write_jsonl(HITS_PATH, sentences.rows + paragraphs.rows)
    print(f"{len(sentences.rows) + len(paragraphs.rows)} hits over {len(rules)} rules, report at {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
