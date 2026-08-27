"""Unwired because nearest-exemplar cosine caught at most 1 of 273 regex-confirmed pattern sentences at any cutoff whose hit rate on the other 2393 sentences stayed under 1 percent."""
from __future__ import annotations

import json
from math import sqrt
from pathlib import Path
from typing import NamedTuple, cast

try:
    from .embedding_client import Vector, embed
    from .findings import Finding, FindingDict
    from .prose_structure import _markdown_prose_lines, _paragraphs, _sentences
except ImportError:
    from embedding_client import Vector, embed
    from findings import Finding, FindingDict
    from prose_structure import _markdown_prose_lines, _paragraphs, _sentences

EXEMPLAR_PATH = Path(__file__).with_name("slop_exemplars.jsonl")
# WHY: Held at the lowest cutoff that scored zero hits on 2393 ordinary sentences, since no cutoff bought recall to trade against.
SIMILARITY_THRESHOLD = 0.70
# WHY: One request per file keeps the model resident for a single turn, and a long file would otherwise time the request out.
MAX_SENTENCES = 300
MIN_SENTENCE_WORDS = 4


class Exemplar(NamedTuple):
    rule: str
    text: str


class SemanticMatch(NamedTuple):
    line: int
    sentence: str
    exemplar: Exemplar
    similarity: float


def load_exemplars(path: Path) -> tuple[Exemplar, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    return tuple(Exemplar(row["rule"], row["text"]) for row in rows)


def _cosine(left: Vector, right: Vector) -> float:
    norm = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    if not norm:
        return 0.0
    return sum(one * two for one, two in zip(left, right)) / norm


def prose_sentences(text: str) -> tuple[tuple[int, str], ...]:
    lines = list(_markdown_prose_lines(text))
    return tuple(
        (number, sentence.strip())
        for paragraph in _paragraphs(lines)
        for number, sentence in _sentences(paragraph)
        if len(sentence.split()) >= MIN_SENTENCE_WORDS
    )[:MAX_SENTENCES]


def _best_exemplar(
    vector: Vector, exemplars: tuple[Exemplar, ...], exemplar_vectors: tuple[Vector, ...]
) -> tuple[Exemplar, float]:
    scored = [
        (_cosine(vector, exemplar_vector), exemplar)
        for exemplar_vector, exemplar in zip(exemplar_vectors, exemplars)
    ]
    similarity, exemplar = max(scored, key=lambda pair: pair[0])
    return exemplar, similarity


def matches(
    sentences: tuple[tuple[int, str], ...],
    sentence_vectors: tuple[Vector, ...],
    exemplars: tuple[Exemplar, ...],
    exemplar_vectors: tuple[Vector, ...],
    threshold: float,
) -> tuple[SemanticMatch, ...]:
    found = []
    for (line, sentence), vector in zip(sentences, sentence_vectors):
        exemplar, similarity = _best_exemplar(vector, exemplars, exemplar_vectors)
        if similarity >= threshold:
            found.append(SemanticMatch(line, sentence, exemplar, similarity))
    return tuple(found)


def _finding(path: str, item: SemanticMatch) -> FindingDict:
    finding = Finding(
        family="english",
        rule=item.exemplar.rule,
        line=item.line,
        detail=(
            f"Sentence matches the {item.exemplar.rule} exemplar {item.exemplar.text!r} "
            f"at cosine {item.similarity:.2f} (threshold {SIMILARITY_THRESHOLD:g}) in {path}"
        ),
        force=True,
        snippet=item.sentence[:180],
        action="Rewrite the sentence as a direct statement.",
        path=None,
        severity=None,
        tool_use_id=None,
    )
    return cast(FindingDict, finding.to_dict())


def scan_semantic(path: str, text: str) -> list[FindingDict] | None:
    """None separates an absent embedding server from a clean file, because reporting the two the same way would claim a check that never ran."""
    sentences = prose_sentences(text)
    if not sentences:
        return []
    exemplars = load_exemplars(EXEMPLAR_PATH)
    vectors = embed(tuple(item.text for item in exemplars) + tuple(row[1] for row in sentences))
    if vectors is None:
        return None
    exemplar_vectors = vectors[:len(exemplars)]
    found = matches(sentences, vectors[len(exemplars):], exemplars, exemplar_vectors, SIMILARITY_THRESHOLD)
    return [_finding(path, item) for item in found]
