#!/usr/bin/env python3
"""Measure the parataxis rules on real paragraphs, because humanizer-de dropped pattern 51 after a naive check fired on every human blog post."""
import argparse
import importlib
import itertools
import json
import random
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALS = REPOSITORY_ROOT / "evals"
HOOKS = str(REPOSITORY_ROOT / "hooks")
OUTPUT_PATH = EVALS / "parataxis_hit_rate.json"
SAMPLE_PATH = EVALS / "parataxis_sample.jsonl"
SAMPLE_NAME = "sample.md"
SEED = 20261014
PER_LANGUAGE = 40
PER = 1000
SWEEP = {
    "min_run": (3, 4, 5),
    "linked_min_run": (3, 4),
    "max_words": (10, 12, 14),
    "max_fronted": (0, 1, 2),
}


def hook_module(name: str) -> ModuleType:
    """Import on demand, because a module-level path change would run on every import of this script."""
    if HOOKS not in sys.path:
        sys.path.insert(0, HOOKS)
    return importlib.import_module("lib." + name)


class Corpus(NamedTuple):
    language: str
    file_name: str
    lexicon_name: str


CORPORA = (
    Corpus("en", "corpus_paragraphs.jsonl", "ENGLISH"),
    Corpus("de", "corpus_paragraphs_de.jsonl", "GERMAN"),
)


class Paragraph(NamedTuple):
    document: int
    index: int
    side: str
    genre: str
    sentences: tuple


def _lexicon(corpus: Corpus):
    return getattr(hook_module("parataxis_lexicon"), corpus.lexicon_name)


def load_paragraphs(corpus: Corpus, corpus_dir: Path) -> list[Paragraph]:
    """Route through the scanner's own block split, because a list item or heading must drop out here too."""
    parataxis = hook_module("parataxis")
    prose_lines = hook_module("prose_structure")._markdown_prose_lines  # pylint: disable=protected-access
    lexicon = _lexicon(corpus)
    paragraphs = []
    with (corpus_dir / corpus.file_name).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            side = "human" if row["origin"] == "human" else "ai"
            blocks = parataxis.blocks(SAMPLE_NAME, list(prose_lines("\n\n".join(row["paragraphs"]))))
            paragraphs.extend(
                Paragraph(number, index, side, row.get("genre", "assistant"), tuple(parataxis.paragraph_sentences(block, lexicon)))
                for index, block in enumerate(blocks)
            )
    return paragraphs


def hits(paragraphs: list[Paragraph], lexicon, limits) -> list[tuple[Paragraph, list]]:
    bare_runs = hook_module("parataxis").bare_runs
    found = []
    for paragraph in paragraphs:
        runs = bare_runs(list(paragraph.sentences), lexicon, limits)
        if runs:
            found.append((paragraph, runs))
    return found


def rates(paragraphs: list[Paragraph], found: list[tuple[Paragraph, list]]) -> dict[str, dict[str, float]]:
    totals = Counter(f"{row.side}/{row.genre}" for row in paragraphs) + Counter(row.side for row in paragraphs)
    counted = Counter(f"{row.side}/{row.genre}" for row, _runs in found) + Counter(row.side for row, _runs in found)
    return {
        key: {"paragraphs": totals[key], "hits": counted[key], "per_1000": round(PER * counted[key] / totals[key], 3)}
        for key in sorted(totals)
    }


def sweep(loaded: dict[str, list[Paragraph]]) -> None:
    thresholds = hook_module("parataxis").Thresholds
    for corpus in CORPORA:
        print(f"== {corpus.language}")
        for values in itertools.product(*SWEEP.values()):
            limits = thresholds(**dict(zip(SWEEP, values)))
            measured = rates(loaded[corpus.language], hits(loaded[corpus.language], _lexicon(corpus), limits))
            human = measured["human"]
            print(f"{values} human {human['hits']} ({human['per_1000']}) ai {measured['ai']['hits']}")


def sample(corpus: Corpus, found: list[tuple[Paragraph, list]]) -> list[dict]:
    """Draw under a fixed seed per language, because a rerun must hand raters the same rows."""
    chosen = random.Random(f"{SEED}:{corpus.language}").sample(range(len(found)), min(PER_LANGUAGE, len(found)))
    rule = _lexicon(corpus).rule
    rows = []
    for position in sorted(chosen):
        paragraph, runs = found[position]
        rows.append({
            "id": f"{rule}:{paragraph.document}:{paragraph.index}", "rule": rule, "side": paragraph.side,
            "genre": paragraph.genre, "paragraph": " ".join(sentence.shown for sentence in paragraph.sentences),
            "run": " ".join(sentence.shown for sentence in runs[0]),
        })
    return rows


def report(loaded: dict[str, list[Paragraph]]) -> None:
    limits = hook_module("parataxis").Thresholds()
    record: dict[str, object] = {"thresholds": limits._asdict(), "seed": SEED, "rules": {}}
    sampled: list[dict] = []
    for corpus in CORPORA:
        found = hits(loaded[corpus.language], _lexicon(corpus), limits)
        record["rules"][_lexicon(corpus).rule] = {"corpus": corpus.file_name, "rates": rates(loaded[corpus.language], found)}
        sampled.extend(sample(corpus, found))
    OUTPUT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True)
    SAMPLE_PATH.write_text("".join(encoder.encode(row) + "\n" for row in sampled), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", type=Path, default=EVALS)
    parser.add_argument("--sweep", action="store_true")
    arguments = parser.parse_args()
    loaded = {corpus.language: load_paragraphs(corpus, arguments.corpus_dir) for corpus in CORPORA}
    if arguments.sweep:
        sweep(loaded)
        return
    report(loaded)


if __name__ == "__main__":
    main()
