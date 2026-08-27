"""Votes a sentence against one pattern's own two classes, because a single exemplar cosine measured topic and caught 1 sentence in 273."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import NamedTuple

try:
    from .embedding_client import Vector, embed
    from .pattern_judge import PatternCandidate, PatternRule, confirm_all
    from .prose_structure import _markdown_prose_lines, _paragraphs, _sentences
    from .session_state import plugin_data_home
except ImportError:
    from embedding_client import Vector, embed
    from pattern_judge import PatternCandidate, PatternRule, confirm_all
    from prose_structure import _markdown_prose_lines, _paragraphs, _sentences
    from session_state import plugin_data_home


def exemplar_cache_root() -> Path:
    return plugin_data_home() / "cache" / "exemplars"

EXEMPLAR_PATH = Path(__file__).with_name("pattern_exemplars.jsonl")
MANIFEST_PATH = Path(__file__).with_name("pattern_exemplars.json")
NEIGHBOURS = 5
JUDGE_EXAMPLES = 4
MIN_SENTENCE_WORDS = 4
MAX_SENTENCES = 200
VIOLATING = "violating"
CLEAN = "clean"
# WHY: Measured precision after the judge, so a rule blocks only where the number earns it.
ENFORCE_PRECISION = 0.85


class Exemplar(NamedTuple):
    rule: str
    label: str
    text: str


class Sentence(NamedTuple):
    line: int
    text: str


class Finding(NamedTuple):
    rule: str
    line: int
    text: str
    blocking: bool


def load_exemplars() -> tuple[Exemplar, ...]:
    with EXEMPLAR_PATH.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    return tuple(Exemplar(row["rule"], row["label"], row["text"]) for row in rows)


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def measured_rules(manifest: dict) -> tuple[str, ...]:
    """Only a measured rule may speak, because an unmeasured one would report at a precision nobody has ever checked."""
    return tuple(sorted(
        rule for rule, row in manifest["rules"].items()
        if isinstance(row.get("judge_precision"), (int, float))
    ))


def blocking_rules(manifest: dict) -> frozenset[str]:
    """Blocks only where the judge measured the rule at or above the floor, because the rest have not earned a hard stop."""
    return frozenset(
        rule for rule in measured_rules(manifest)
        if manifest["rules"][rule]["judge_precision"] >= ENFORCE_PRECISION
    )


def prose_sentences(path: str, text: str) -> tuple[Sentence, ...]:
    lines = list(_markdown_prose_lines(text))
    found = [
        Sentence(number, sentence)
        for paragraph in _paragraphs(lines)
        for number, sentence in _sentences(paragraph)
        if len(sentence.split()) >= MIN_SENTENCE_WORDS
    ]
    return tuple(found[:MAX_SENTENCES])


def _similarity(left: Vector, right: Vector) -> float:
    return sum(one * other for one, other in zip(left, right))


def _votes_violating(vector: Vector, neighbours: list[tuple[str, Vector]]) -> bool:
    ranked = sorted(neighbours, key=lambda entry: -_similarity(vector, entry[1]))
    return Counter(label for label, _ in ranked[:NEIGHBOURS]).most_common(1)[0][0] == VIOLATING


def rule_prompt(rule: str, exemplars: tuple[Exemplar, ...], manifest: dict) -> PatternRule:
    sides = {
        label: tuple(row.text for row in exemplars if row.rule == rule and row.label == label)[:JUDGE_EXAMPLES]
        for label in (VIOLATING, CLEAN)
    }
    return PatternRule(rule, manifest["rules"][rule]["action"], sides[VIOLATING], sides[CLEAN])


def candidates_for(
    rule: str, sentences: tuple[Sentence, ...], vectors: dict[str, Vector], exemplars: tuple[Exemplar, ...], path: str
) -> tuple[PatternCandidate, ...]:
    neighbours = [(row.label, vectors[row.text]) for row in exemplars if row.rule == rule and row.text in vectors]
    return tuple(
        PatternCandidate(path, sentence.line, sentence.text)
        for sentence in sentences
        if sentence.text in vectors and _votes_violating(vectors[sentence.text], neighbours)
    )


def _vectors(texts: tuple[str, ...]) -> dict[str, Vector]:
    answered = embed(texts)
    return dict(zip(texts, answered)) if answered else {}


def _cache_path() -> Path:
    return exemplar_cache_root() / f"{EXEMPLAR_PATH.name}.{_exemplar_digest()}.json"


def _exemplar_digest() -> str:
    return hashlib.sha256(EXEMPLAR_PATH.read_bytes()).hexdigest()[:16]


def _cached_vectors() -> dict[str, Vector]:
    try:
        rows = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {text: tuple(vector) for text, vector in rows}


def exemplar_vectors(exemplars: tuple[Exemplar, ...]) -> dict[str, Vector]:
    """Cached under the exemplar digest because embedding 2099 rows on every write cost the scan ten seconds it never needed to pay."""
    cached = _cached_vectors()
    wanted = tuple(sorted({row.text for row in exemplars} - set(cached)))
    if not wanted:
        return cached
    fresh = _vectors(wanted)
    if not fresh:
        return cached
    merged = {**cached, **fresh}
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([[text, list(vector)] for text, vector in merged.items()]), encoding="utf-8")
    return merged


def scan(path: str, text: str) -> tuple[Finding, ...]:
    """Answers nothing when the server is absent, because a missing vector must read as no finding rather than as clean prose."""
    sentences = prose_sentences(path, text)
    if not sentences:
        return ()
    exemplars = load_exemplars()
    manifest = load_manifest()
    vectors = {**exemplar_vectors(exemplars), **_vectors(tuple({item.text for item in sentences}))}
    if not vectors:
        return ()
    work = tuple(
        (rule_prompt(rule, exemplars, manifest), candidates_for(rule, sentences, vectors, exemplars, path))
        for rule in measured_rules(manifest)
    )
    blocking = blocking_rules(manifest)
    return tuple(
        Finding(rule, candidate.line, candidate.text, rule in blocking)
        for rule, kept in sorted(confirm_all(work).items())
        for candidate in kept
    )
