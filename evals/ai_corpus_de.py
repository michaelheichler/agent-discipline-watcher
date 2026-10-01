#!/usr/bin/env python3
"""Read the German AI sentence corpus in one place, because a label names a corpus line and two readers could number lines apart."""
import hashlib
import json
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AI_CORPUS_PATH = REPOSITORY_ROOT / "evals" / "corpus_ai_sentences_de.jsonl"
AI_MANIFEST_PATH = REPOSITORY_ROOT / "evals" / "corpus_ai_manifest_de.json"
LABELS_PATH = REPOSITORY_ROOT / "evals" / "pattern_labels_de.jsonl"


class AiRow(NamedTuple):
    line: int
    source: str
    model: str
    document: int
    text: str


def load_ai_corpus(path: Path = AI_CORPUS_PATH) -> list[AiRow]:
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    return [AiRow(number, row["source"], row["model"], row["row"], row["text"]) for number, row in enumerate(rows, 1)]


def ai_corpus_digest(path: Path = AI_CORPUS_PATH, manifest: Path = AI_MANIFEST_PATH) -> str:
    """Checked against the manifest, because a drifted corpus moves every labeled line."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
    if digest != expected:
        raise ValueError(f"{path.name} hashes to {digest}, the corpus manifest records {expected}; rebuild the corpus")
    return digest


def load_labels(path: Path = LABELS_PATH) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]
