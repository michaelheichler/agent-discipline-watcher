#!/usr/bin/env python3
"""Reports what each cutoff costs on real prose, because a similarity threshold picked by eye is a guess wearing a number."""
import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.embedding_client import embed
from lib.slop_phrase import scan_slop_phrases
from lib.slop_semantic import EXEMPLAR_PATH, _best_exemplar, load_exemplars, prose_sentences
from lib.slop_structure import _scan_slop_structure

SENTENCE_CORPUS = REPOSITORY_ROOT / "hooks" / "lib" / "corpus_slop_sentence.jsonl"
DOCUMENT_CORPUS = REPOSITORY_ROOT / "hooks" / "lib" / "corpus_slop_document.jsonl"
BATCH_SIZE = 64
CANDIDATE_THRESHOLDS = tuple(round(0.50 + step * 0.02, 2) for step in range(21))


class Sample(NamedTuple):
    text: str
    regex_positive: bool


def _repository_markdown() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPOSITORY_ROOT,
        capture_output=True, text=True, check=True,
    )
    return [REPOSITORY_ROOT / name for name in listed.stdout.split()]


def _regex_flagged(text: str) -> bool:
    rows = _scan_slop_structure("sample.md", text)
    rows.extend(scan_slop_phrases("sample.md", text, {}))
    return bool(rows)


def _corpus_samples(path: Path) -> list[Sample]:
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        text = json.loads(line)["text"]
        samples.extend(
            Sample(sentence, _regex_flagged(sentence))
            for _number, sentence in prose_sentences(text)
        )
    return samples


def _repository_samples() -> list[Sample]:
    samples = []
    for path in _repository_markdown():
        text = path.read_text(encoding="utf-8", errors="replace")
        samples.extend(
            Sample(sentence, _regex_flagged(sentence))
            for _number, sentence in prose_sentences(text)
        )
    return samples


def _embed_all(texts: list[str]) -> list[tuple[float, ...]]:
    vectors: list[tuple[float, ...]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = tuple(texts[start:start + BATCH_SIZE])
        result = embed(batch)
        if result is None:
            raise SystemExit("embedding endpoint unreachable, so no threshold can be measured")
        vectors.extend(result)
        print(f"  embedded {len(vectors)} of {len(texts)}", flush=True)
    return vectors


def _scores(samples: list[Sample]) -> list[tuple[float, bool]]:
    exemplars = load_exemplars(EXEMPLAR_PATH)
    exemplar_vectors = tuple(_embed_all([item.text for item in exemplars]))
    sentence_vectors = _embed_all([item.text for item in samples])
    return [
        (_best_exemplar(vector, exemplars, exemplar_vectors)[1], sample.regex_positive)
        for vector, sample in zip(sentence_vectors, samples)
    ]


def _report(label: str, scores: list[tuple[float, bool]]) -> None:
    positives = [value for value, flagged in scores if flagged]
    negatives = [value for value, flagged in scores if not flagged]
    print(f"\n{label}: {len(positives)} regex positive, {len(negatives)} regex negative")
    print("threshold  recall_on_regex_positive  hit_rate_on_regex_negative")
    for threshold in CANDIDATE_THRESHOLDS:
        recall = sum(1 for value in positives if value >= threshold) / max(len(positives), 1)
        rate = sum(1 for value in negatives if value >= threshold) / max(len(negatives), 1)
        print(f"{threshold:>9.2f}  {recall:>24.3f}  {rate:>26.4f}")


def _ranking_report(label: str, scores: list[tuple[float, bool]]) -> None:
    """Ranks rather than thresholds, because a shortlist for a judge only needs the positives near the top."""
    ordered = sorted(scores, key=lambda pair: -pair[0])
    total_positive = sum(1 for _value, flagged in ordered if flagged)
    print(f"\n{label} shortlist quality ({total_positive} positives in {len(ordered)} sentences)")
    print("top_k  recall_at_k  random_baseline")
    for fraction in (0.05, 0.10, 0.20, 0.30):
        cut = max(int(len(ordered) * fraction), 1)
        caught = sum(1 for _value, flagged in ordered[:cut] if flagged)
        recall = caught / max(total_positive, 1)
        print(f"{cut:>5}  {recall:>11.3f}  {fraction:>15.3f}")


def main() -> None:
    for label, samples in (
        ("repository markdown", _repository_samples()),
        ("sentence corpus", _corpus_samples(SENTENCE_CORPUS)),
        ("document corpus", _corpus_samples(DOCUMENT_CORPUS)),
    ):
        print(f"\nscoring {label} ({len(samples)} sentences)", flush=True)
        scores = _scores(samples)
        _report(label, scores)
        _ranking_report(label, scores)


if __name__ == "__main__":
    main()
