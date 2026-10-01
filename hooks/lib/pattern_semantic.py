"""Two classes per rule, because one cosine measured topic."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import NamedTuple

try:
    from .config import rule_state
    from .embedding_client import Vector, embed, embeddings_urls, model_name
    from .embedding_session import enabled
    from .markup import MIXED_LANGUAGE_EXTS, RegionKind, _mask_markup, extract_regions, render_regions
    from .pattern_judge import JUDGED_GATE_MODEL, JudgedOutcome, PatternCandidate, PatternRule, confirm_all
    from .pattern_language import (
        GERMAN_EXEMPLAR_PATH, GERMAN_MANIFEST_PATH, german_manifest_rules, line_languages, rule_language, rule_trigger,
    )
    from .prose_language import GERMAN
    from .prose_structure import _markdown_prose_lines, _paragraphs, _sentences
    from .session_state import plugin_data_home
except ImportError:
    from config import rule_state
    from embedding_client import Vector, embed, embeddings_urls, model_name
    from embedding_session import enabled
    from markup import MIXED_LANGUAGE_EXTS, RegionKind, _mask_markup, extract_regions, render_regions
    from pattern_judge import JUDGED_GATE_MODEL, JudgedOutcome, PatternCandidate, PatternRule, confirm_all
    from pattern_language import (
        GERMAN_EXEMPLAR_PATH, GERMAN_MANIFEST_PATH, german_manifest_rules, line_languages, rule_language, rule_trigger,
    )
    from prose_language import GERMAN
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
# Blocks only here, because lower precision misfires.
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


def _read_exemplars(path: Path) -> tuple[Exemplar, ...]:
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    return tuple(Exemplar(row["rule"], row["label"], row["text"]) for row in rows)


def load_exemplars() -> tuple[Exemplar, ...]:
    """One pool, because every judge path looks a rule up by name and each name belongs to one language."""
    return _read_exemplars(EXEMPLAR_PATH) + _read_exemplars(GERMAN_EXEMPLAR_PATH)


def load_manifest() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    german = german_manifest_rules(json.loads(GERMAN_MANIFEST_PATH.read_text(encoding="utf-8")))
    return {**manifest, "rules": {**manifest["rules"], **german}}


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


def rule_blocks(manifest: dict, rule: str, config: dict | None) -> bool:
    """Project config wins, because the regex path obeys it."""
    if rule_state(rule, config) in {"observe", "off"}:
        return False
    return rule in blocking_rules(manifest)


def prose_source(path: str, text: str) -> str:
    """Every style attribute became a candidate because markup reached the embedder unmasked."""
    regions = extract_regions(path, text)
    if PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS:
        return render_regions(text, regions, {RegionKind.VISIBLE_PROSE})
    return _mask_markup(path, text)


def prose_sentences(path: str, text: str) -> tuple[Sentence, ...]:
    lines = list(_markdown_prose_lines(prose_source(path, text)))
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
    row = manifest["rules"][rule]
    return PatternRule(
        rule, row["action"], sides[VIOLATING], sides[CLEAN], rule_language(manifest, rule), str(row.get("definition") or ""),
    )


def _has_violating_side(rule: str, exemplars: tuple[Exemplar, ...]) -> bool:
    """Silent without one, because a German rule ships its clean side before its violating one."""
    return any(row.rule == rule and row.label == VIOLATING for row in exemplars)


def triggered_for(sentences: tuple[Sentence, ...], trigger: re.Pattern[str], path: str) -> tuple[PatternCandidate, ...]:
    """Trigger, not vote, because the judge must face the same candidates its precision was measured on."""
    return tuple(PatternCandidate(path, sentence.line, sentence.text) for sentence in sentences if trigger.search(sentence.text))


def candidates_for(rule: str, sentences: tuple[Sentence, ...], vectors: dict[str, Vector], exemplars: tuple[Exemplar, ...], path: str) -> tuple[PatternCandidate, ...]:
    if not _has_violating_side(rule, exemplars):
        return ()
    neighbours = [(row.label, vectors[row.text]) for row in exemplars if row.rule == rule and row.text in vectors]
    if not neighbours:
        sys.stderr.write(f"agent-discipline-watcher: skipped {rule}, no exemplar vectors\n")
        return ()
    return tuple(
        PatternCandidate(path, sentence.line, sentence.text)
        for sentence in sentences
        if sentence.text in vectors and _votes_violating(vectors[sentence.text], neighbours)
    )


def _vectors(texts: tuple[str, ...], config: dict | None = None) -> dict[str, Vector]:
    answered = embed(texts) if config is None else embed(texts, config)
    return dict(zip(texts, answered)) if answered else {}


VectorSource = Callable[..., dict[str, Vector]]


def _cache_path(config: dict | None) -> Path:
    return exemplar_cache_root() / f"{EXEMPLAR_PATH.name}.{_cache_digest(config)}.json"


def _cache_digest(config: dict | None) -> str:
    """Keyed on model and endpoint, because each yields other vectors."""
    digest = hashlib.sha256(EXEMPLAR_PATH.read_bytes())
    digest.update(GERMAN_EXEMPLAR_PATH.read_bytes())
    digest.update(json.dumps([model_name(), embeddings_urls(config)]).encode("utf-8"))
    return digest.hexdigest()[:16]


def _cached_vectors(path: Path) -> dict[str, Vector]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {text: tuple(vector) for text, vector in rows}


def _write_cache(path: Path, vectors: dict[str, Vector]) -> None:
    """Replaced whole, because a torn cache would poison later scans."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps([[text, list(vector)] for text, vector in vectors.items()]), encoding="utf-8")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def exemplar_vectors(exemplars: tuple[Exemplar, ...], config: dict | None = None, *, vectors: VectorSource = _vectors) -> dict[str, Vector]:
    """Cached, because every scan reuses the same exemplars."""
    path = _cache_path(config)
    cached = _cached_vectors(path)
    wanted = tuple(sorted({row.text for row in exemplars} - set(cached)))
    if not wanted:
        return cached
    fresh = vectors(wanted) if config is None else vectors(wanted, config)
    if not fresh:
        return cached
    merged = {**cached, **fresh}
    _write_cache(path, merged)
    return merged


class Layer(NamedTuple):
    exemplars: Callable[[], tuple[Exemplar, ...]] = load_exemplars
    manifest: Callable[[], dict] = load_manifest
    exemplar_vectors: Callable[..., dict[str, Vector]] = exemplar_vectors
    vectors: VectorSource = _vectors
    confirm: Callable[..., JudgedOutcome] = confirm_all


def candidates(path: str, text: str, config: dict | None = None, *, layer: Layer = Layer()) -> dict[str, tuple[PatternCandidate, ...]]:
    """Unjudged, because the Stop reviewer judges once per turn."""
    sentences = prose_sentences(path, text)
    if not sentences or not enabled():
        return {}
    manifest = layer.manifest()
    rules = tuple(rule for rule in measured_rules(manifest) if rule_state(rule, config) != "off")
    german = tuple(rule for rule in rules if rule_language(manifest, rule) == GERMAN)
    exemplars = tuple(row for row in layer.exemplars() if row.rule in rules)
    draft = Draft(path, sentences_by_language(prose_source(path, text), sentences, config), exemplars, manifest, config)
    found = {**_voted(draft, tuple(rule for rule in rules if rule not in german), layer), **_triggered(draft, german)}
    return {rule: rows for rule, rows in found.items() if rows}


class Draft(NamedTuple):
    path: str
    by_language: dict[str, tuple[Sentence, ...]]
    exemplars: tuple[Exemplar, ...]
    manifest: dict
    config: dict | None


def _triggered(draft: Draft, rules: tuple[str, ...]) -> dict[str, tuple[PatternCandidate, ...]]:
    """No trigger or no violating side keeps a German rule silent, because it has nothing measured to stand on."""
    found = {}
    for rule in rules:
        trigger = rule_trigger(draft.manifest, rule)
        if trigger is not None and _has_violating_side(rule, draft.exemplars):
            found[rule] = triggered_for(draft.by_language.get(GERMAN, ()), trigger, draft.path)
    return found


def _voted(draft: Draft, rules: tuple[str, ...], layer: Layer) -> dict[str, tuple[PatternCandidate, ...]]:
    """Embeds only what the voting rules read, because a German sentence no longer meets a vote."""
    languages = {rule_language(draft.manifest, rule) for rule in rules}
    texts = tuple({sentence.text for language in languages for sentence in draft.by_language.get(language, ())})
    if not texts:
        return {}
    exemplars = tuple(row for row in draft.exemplars if row.rule in rules)
    config = draft.config
    cached = layer.exemplar_vectors(exemplars) if config is None else layer.exemplar_vectors(exemplars, config)
    current = layer.vectors(texts) if config is None else layer.vectors(texts, config)
    vectors = {**cached, **current}
    if not vectors:
        return {}
    return {
        rule: candidates_for(rule, draft.by_language.get(rule_language(draft.manifest, rule), ()), vectors, exemplars, draft.path)
        for rule in rules
    }


def sentences_by_language(source: str, sentences: tuple[Sentence, ...], config: dict | None) -> dict[str, tuple[Sentence, ...]]:
    """Split before the vote, because a German pattern row may meet only German exemplars and the German rubric."""
    language_at = line_languages(source, config)
    grouped: dict[str, list[Sentence]] = {}
    for sentence in sentences:
        grouped.setdefault(language_at(sentence.line), []).append(sentence)
    return {language: tuple(found) for language, found in grouped.items()}


def scan(path: str, text: str, config: dict | None = None, *, layer: Layer = Layer()) -> tuple[Finding, ...]:
    """Kept because the evals measure the judged pipeline."""
    voted = candidates(path, text, config, layer=layer)
    if not voted:
        return ()
    exemplars = layer.exemplars()
    manifest = layer.manifest()
    work = tuple((rule_prompt(rule, exemplars, manifest), found) for rule, found in voted.items())
    blocking = blocking_rules(manifest)
    model = str((config.get("adw_model") if isinstance(config, dict) else None) or JUDGED_GATE_MODEL)
    return tuple(
        Finding(rule, candidate.line, candidate.text, rule in blocking)
        for rule, kept in sorted(layer.confirm(work, model).kept.items())
        for candidate in kept
    )
