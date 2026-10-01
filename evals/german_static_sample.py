#!/usr/bin/env python3
"""Draw a fixed sample of German rule hits and hand raters blind items, because precision needs a human-style verdict per hit."""
import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from measure_german_hit_rate import (
    DOCUMENT_RULES, EVALS, HITS_PATH, PARAGRAPH_CORPUS, SENTENCE_CORPORA, hook_module, write_jsonl,
)

SAMPLE_PATH = EVALS / "german_static_sample.jsonl"
ITEMS_DIR = EVALS / "german_static_items"
SEED = 20261001
PER_RULE = 20
EXTENDED_PER_RULE = 40
EXTENDED_RULES = (
    "de_meta_commentary", "de_prompt_refusal", "de_stretched_verb", "spaced_hyphen",
    "de_repeated_connector", "de_abrupt_ending", "de_knowledge_cutoff", "de_sentence_length",
)
BATCH_SIZE = 140
WHOLE_DOCUMENT_RULES = frozenset({"de_uniform_rhythm", "de_uniform_paragraphs", "dash_cluster"})
SENTENCE_NAMES = frozenset(corpus.name for corpus in SENTENCE_CORPORA)
REF_FIELDS = ("id", "rule", "corpus", "line", "side", "genre", "finding_line")
DECIDED = ("violating", "clean")
FIRST, SECOND, THIRD, ADJUDICATED = "sonnet", "luna", "opus", "adjudicated"


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def designated(rule: str, hits: list[dict]) -> list[dict]:
    """Markup, density, and rhythm survive only in full replies, because the flat corpora store one line per row."""
    sentences = [hit for hit in hits if hit["corpus"] in SENTENCE_NAMES]
    paragraphs = [hit for hit in hits if hit["corpus"] == PARAGRAPH_CORPUS.name]
    if rule in DOCUMENT_RULES or (len(sentences) < PER_RULE and len(paragraphs) > len(sentences)):
        return paragraphs
    return sentences


def draw(hits: list[dict]) -> list[dict]:
    """Seed per rule, because adding a rule must not reshuffle the sample of another."""
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for hit in hits:
        by_rule[hit["rule"]].append(hit)
    sample = []
    for rule in sorted(by_rule):
        pool = designated(rule, by_rule[rule])
        chosen = random.Random(f"{SEED}:{rule}").sample(range(len(pool)), min(PER_RULE, len(pool)))
        sample.extend(pool[index] for index in sorted(chosen))
    return [_ref(row) for row in sample]


def _ref(row: dict) -> dict:
    return {"id": f"{row['rule']}:{row['corpus']}:{row['line']}", **{key: row.get(key) for key in REF_FIELDS[1:]}}


def extend(sample: list[dict], hits: list[dict]) -> list[dict]:
    """Keep the labeled rows and draw only new ones from the same corpus, because 20 of 20 bounds at 0.8389, under the bar."""
    added = []
    for rule in EXTENDED_RULES:
        kept = [ref for ref in sample if ref["rule"] == rule]
        if not kept:
            continue
        taken = {ref["id"] for ref in kept}
        paragraphs = kept[0]["corpus"] == PARAGRAPH_CORPUS.name
        pool = [_ref(hit) for hit in hits
                if hit["rule"] == rule and (hit["corpus"] == PARAGRAPH_CORPUS.name) == paragraphs]
        pool = [ref for ref in pool if ref["id"] not in taken]
        wanted = min(EXTENDED_PER_RULE - len(kept), len(pool))
        chosen = random.Random(f"{SEED}:{rule}:extend").sample(range(len(pool)), max(0, wanted))
        added.extend(pool[index] for index in sorted(chosen))
    return added


def _extend_step() -> None:
    sample = read_jsonl(SAMPLE_PATH)
    added = extend(sample, read_jsonl(HITS_PATH))
    write_jsonl(SAMPLE_PATH, sample + added)
    print("\n".join(map(str, export(added, "extend"))))


def pending_disputes(sample: list[dict], answer_paths: list[Path]) -> list[dict]:
    """Skip rows a third rater already decided, because an extension must not send old splits out again."""
    answered = {row["id"] for path in answer_paths for row in read_jsonl(path)}
    return [ref for ref in disputed(sample) if opaque(ref["id"]) not in answered]


def paragraph_at(paragraphs: list[str], finding_line: int) -> str:
    """Count lines the way the scanner sees the joined document, because a finding names its line, not its paragraph."""
    start = 1
    for paragraph in paragraphs:
        end = start + paragraph.count("\n")
        if start <= finding_line <= end:
            return paragraph
        start = end + 2
    raise ValueError(f"finding line {finding_line} falls outside the document")


def unit_texts() -> dict[tuple[str, int], object]:
    texts: dict[tuple[str, int], object] = {}
    for corpus in SENTENCE_CORPORA:
        texts.update(((corpus.name, number), row["text"]) for number, row in enumerate(read_jsonl(corpus.path), 1))
    rows = enumerate(read_jsonl(PARAGRAPH_CORPUS.path), 1)
    texts.update(((PARAGRAPH_CORPUS.name, number), row["paragraphs"]) for number, row in rows)
    return texts


def _shown_text(ref: dict, unit: object) -> str:
    if isinstance(unit, str):
        return unit
    if ref["rule"] in WHOLE_DOCUMENT_RULES:
        return "\n\n".join(unit)
    return paragraph_at(unit, ref["finding_line"])


def blind_item(ref: dict, hit: dict, unit: object) -> dict:
    """Rule wording and text only, because a rater who sees the corpus side or the other rater anchors on it."""
    german = hook_module("catalog_de").RULES[ref["rule"]]
    english = hook_module("catalog").rule_entry(ref["rule"])
    flagged = None if ref["rule"] in WHOLE_DOCUMENT_RULES else hit.get("match") or hit.get("snippet")
    return {
        "id": opaque(ref["id"]), "rule": ref["rule"], "rule_en": english.title + ". " + english.description,
        "regel": german.title, "beschreibung": german.description, "korrektur": german.action,
        "flagged": flagged, "text": _shown_text(ref, unit),
    }


def blind_items(refs: list[dict]) -> list[dict]:
    hits = {(row["rule"], row["corpus"], row["line"]): row for row in read_jsonl(HITS_PATH)}
    texts = unit_texts()
    return [blind_item(ref, hits[(ref["rule"], ref["corpus"], ref["line"])], texts[(ref["corpus"], ref["line"])])
            for ref in refs]


def export(refs: list[dict], prefix: str) -> list[Path]:
    """Order by hash within a rule, because corpus order would put every human row before every AI row."""
    items = sorted(blind_items(refs), key=lambda item: (item["rule"], item["id"]))
    ITEMS_DIR.mkdir(exist_ok=True)
    paths = []
    for start in range(0, len(items), BATCH_SIZE):
        path = ITEMS_DIR / f"{prefix}_{start // BATCH_SIZE + 1:02d}.jsonl"
        write_jsonl(path, items[start:start + BATCH_SIZE])
        paths.append(path)
    return paths


def labels_path(labeler: str) -> Path:
    return EVALS / f"german_static_labels_{labeler}.jsonl"


def _reason(text: str) -> str:
    """Swap dash characters for commas, because the labels live in git and the punctuation gate scans them."""
    return text.replace("—", ",").replace("–", ",").strip()


def opaque(ref_id: str) -> str:
    """Hash the id, because the plain id names the corpus and so tells the rater who wrote the text."""
    return hashlib.sha256(ref_id.encode("utf-8")).hexdigest()[:12]


def answers_for(refs: list[dict], answer_paths: list[Path], labeler: str) -> dict[str, dict]:
    """Refuse a partial or unknown answer set, because a silent gap would raise precision on the rows left."""
    answers = {row["id"]: row for path in answer_paths for row in read_jsonl(path)}
    wanted = {opaque(ref["id"]): ref["id"] for ref in refs}
    if set(answers) != set(wanted) or any(row["label"] not in DECIDED for row in answers.values()):
        raise ValueError(f"{labeler}: {len(set(wanted) & set(answers))} of {len(wanted)} rows answered, "
                         f"{len(set(answers) - set(wanted))} unknown ids")
    return {wanted[key]: row for key, row in answers.items()}


def merge(sample: list[dict], labeler: str, answer_paths: list[Path]) -> list[dict]:
    answers = answers_for(sample, answer_paths, labeler)
    return [{**{key: ref[key] for key in REF_FIELDS if key != "finding_line"}, "label": answers[ref["id"]]["label"],
             "reason": _reason(answers[ref["id"]].get("reason", "")), "labeler": labeler} for ref in sample]


def disputed(sample: list[dict]) -> list[dict]:
    first = {row["id"]: row["label"] for row in read_jsonl(labels_path(FIRST))}
    second = {row["id"]: row["label"] for row in read_jsonl(labels_path(SECOND))}
    return [ref for ref in sample if first[ref["id"]] != second[ref["id"]]]


def adjudicate(sample: list[dict], answer_paths: list[Path]) -> list[dict]:
    """Majority of three, because the third rater only sees rows where the first two split."""
    first = {row["id"]: row for row in read_jsonl(labels_path(FIRST))}
    second = {row["id"]: row for row in read_jsonl(labels_path(SECOND))}
    third = answers_for(disputed(sample), answer_paths, THIRD)
    rows = []
    for ref in sample:
        one, other = first[ref["id"]]["label"], second[ref["id"]]["label"]
        decider = None if one == other else third[ref["id"]]
        rows.append({**{key: ref[key] for key in REF_FIELDS if key != "finding_line"},
                     "label": one if decider is None else decider["label"],
                     FIRST: one, SECOND: other, THIRD: None if decider is None else decider["label"],
                     "reason": "" if decider is None else _reason(decider.get("reason", ""))})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("draw", "export", "extend", "merge", "disputes", "adjudicate"))
    parser.add_argument("--labeler", choices=(FIRST, SECOND))
    parser.add_argument("--prefix", default="disputes")
    parser.add_argument("answers", nargs="*", type=Path)
    arguments = parser.parse_args()
    steps = {
        "draw": lambda: write_jsonl(SAMPLE_PATH, draw(read_jsonl(HITS_PATH))),
        "export": lambda: print("\n".join(map(str, export(read_jsonl(SAMPLE_PATH), "batch")))),
        "extend": _extend_step,
        "merge": lambda: write_jsonl(labels_path(arguments.labeler),
                                     merge(read_jsonl(SAMPLE_PATH), arguments.labeler, arguments.answers)),
        "disputes": lambda: print("\n".join(map(str, export(
            pending_disputes(read_jsonl(SAMPLE_PATH), arguments.answers), arguments.prefix)))),
        "adjudicate": lambda: write_jsonl(labels_path(ADJUDICATED), adjudicate(read_jsonl(SAMPLE_PATH), arguments.answers)),
    }
    steps[arguments.step]()


if __name__ == "__main__":
    main()
