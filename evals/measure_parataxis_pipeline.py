#!/usr/bin/env python3
"""Measure the parataxis pipeline on held-out assistant answers, because a sample of hits alone hides every run the scanner missed."""
import argparse
import importlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from types import ModuleType

from german_static_precision import wilson
from parataxis_precision import decided_labels
from german_static_sample import opaque

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALS = REPOSITORY_ROOT / "evals"
HOOKS = str(REPOSITORY_ROOT / "hooks")
# The dev and test sets tuned the detector, so only the final set is held out.
SETS = {
    "dev": "parataxis_answers.jsonl", "test": "parataxis_answers_test.jsonl",
    "final": "parataxis_answers_final.jsonl", "corpus": "parataxis_sample.jsonl",
}
OUTPUT_PATH = EVALS / "parataxis_pipeline.json"
BATCH = 8
CHOPPED = "chopped"
VIOLATING = "violating"
CONTEXT_LABEL = "Paragraph: "
MAX_CONTEXT_CHARS = 900
JUDGED = {"rule_gates": {"choppy_sentences": "judged", "de_parataxis": "judged"}}


def hook_module(name: str) -> ModuleType:
    """Import on demand, because a module-level path change would run on every import of this script."""
    if HOOKS not in sys.path:
        sys.path.insert(0, HOOKS)
    return importlib.import_module("lib." + name)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True)
    path.write_text("".join(encoder.encode(row) + "\n" for row in rows), encoding="utf-8")


def candidates_path(name: str) -> Path:
    return EVALS / f"parataxis_pipeline_{name}_candidates.jsonl"


def verdicts_path(name: str, reviewer: str) -> Path:
    return EVALS / f"parataxis_pipeline_{name}_verdicts_{reviewer}.jsonl"


def answer_candidates(answers: list[dict]) -> list[dict]:
    """Through the hook's own review_rows, because a copy of the scan would measure a detector nobody ships."""
    review_rows = hook_module("parataxis_review").review_rows
    with tempfile.TemporaryDirectory() as state_root:
        config = {**JUDGED, "state_root": state_root}
        return [
            {"answer": answer["id"], "index": index, **row}
            for answer in answers
            for index, row in enumerate(review_rows(f"{answer['id']}.md", answer["text"], config))
        ]


def corpus_candidates(sample: list[dict]) -> list[dict]:
    """Shaped like a live row, because the reviewer must meet the run and its paragraph as a turn would hand them over."""
    return [
        {"answer": opaque(row["id"]), "index": 0, "rule": row["rule"], "line": 1,
         "text": row["run"] if row["paragraph"] == row["run"] else f"{row['run']}\n{CONTEXT_LABEL}{row['paragraph'][:MAX_CONTEXT_CHARS]}"}
        for row in sample
    ]


def _requests(rule: str, rows: list[dict]) -> list[tuple]:
    semantic = hook_module("pattern_semantic")
    judge = hook_module("pattern_judge")
    prompt = semantic.rule_prompt(rule, semantic.load_exemplars(), semantic.load_manifest())
    batches = [rows[start:start + BATCH] for start in range(0, len(rows), BATCH)]
    return [
        (judge.request_for(prompt, tuple(judge.PatternCandidate(row["answer"], row["line"], row["text"]) for row in batch)), batch)
        for batch in batches
    ]


def _sonnet(request) -> list[dict]:
    """Through the shipped Stop reviewer, because its prompt, schema, and gap check are what a real turn meets."""
    sonnet = hook_module("claude_sonnet")
    payload = sonnet.batch_payload(sonnet._claude_judge(sonnet.batch_prompt([(request, ())])))  # pylint: disable=protected-access
    return sonnet._pattern_result(request, payload["items"]).payload["items"]  # pylint: disable=protected-access


def _luna(request) -> list[dict]:
    """Through the shipped Luna provider, because it checks that every candidate got its own verdict."""
    return hook_module("luna_provider").LunaJudge().judge(request).payload["items"]


REVIEWERS = {"sonnet": _sonnet, "luna": _luna}


def verdicts(candidates: list[dict], reviewer: str) -> list[dict]:
    found = []
    for rule in sorted({row["rule"] for row in candidates}):
        for request, batch in _requests(rule, [row for row in candidates if row["rule"] == rule]):
            found.extend(
                {"answer": row["answer"], "index": row["index"], "verdict": item["verdict"], "reason": item["reason"]}
                for row, item in zip(batch, REVIEWERS[reviewer](request))
            )
            print(f"{rule}: {len(found)} of {len(candidates)} judged", file=sys.stderr)
    return found


def _share(hits: int, total: int) -> dict[str, object]:
    return {"hits": hits, "total": total, "rate": round(hits / total, 4) if total else None,
            "wilson_95": list(wilson(hits, total)) if total else None}


def _stage(answers: list[dict], flagged: set[str]) -> dict[str, object]:
    chopped = [answer for answer in answers if answer["kind"] == CHOPPED]
    hits = [answer for answer in answers if answer["id"] in flagged]
    false = Counter(answer.get("control_type") or answer["kind"] for answer in hits if answer["kind"] != CHOPPED)
    return {
        "recall": _share(sum(answer["id"] in flagged for answer in chopped), len(chopped)),
        "precision": _share(sum(answer["kind"] == CHOPPED for answer in hits), len(hits)),
        "false_positives": dict(sorted(false.items())),
    }


def _confirmed(name: str, reviewer: str) -> set[str]:
    return {row["answer"] for row in read_jsonl(verdicts_path(name, reviewer)) if row["verdict"] == VIOLATING}


def answer_record(name: str, reviewer: str) -> dict[str, object]:
    answers = read_jsonl(EVALS / SETS[name])
    static = {row["answer"] for row in read_jsonl(candidates_path(name))}
    confirmed = _confirmed(name, reviewer)
    by_language: dict[str, object] = {}
    for language in sorted({answer["language"] for answer in answers}):
        chosen = [answer for answer in answers if answer["language"] == language]
        by_language[language] = {
            "answers": dict(sorted(Counter(answer["kind"] for answer in chosen).items())),
            "static": _stage(chosen, static), "combined": _stage(chosen, confirmed),
        }
    return {"answers": SETS[name], "unit": "answer", "languages": by_language}


def corpus_record(reviewer: str) -> dict[str, object]:
    """Against the adjudicated labels, because these human hits are the hard negatives the static rule failed on."""
    sample = read_jsonl(EVALS / SETS["corpus"])
    labels = decided_labels(sample)
    confirmed = _confirmed("corpus", reviewer)
    record: dict[str, object] = {"answers": SETS["corpus"], "unit": "static hit on a human paragraph", "rules": {}}
    for rule in sorted({row["rule"] for row in sample}):
        keys = [opaque(row["id"]) for row in sample if row["rule"] == rule]
        upheld = [key for key in keys if key in confirmed]
        record["rules"][rule] = {
            "static_precision": _share(sum(labels[key] == VIOLATING for key in keys), len(keys)),
            "combined_precision": _share(sum(labels[key] == VIOLATING for key in upheld), len(upheld)),
            "reviewer_recall": _share(sum(labels[key] == VIOLATING for key in upheld), sum(labels[key] == VIOLATING for key in keys)),
        }
    return record


def _candidates_for(name: str) -> list[dict]:
    rows = read_jsonl(EVALS / SETS[name])
    return corpus_candidates(rows) if name == "corpus" else answer_candidates(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("static", "review", "score"))
    parser.add_argument("--set", choices=tuple(SETS), default="final")
    parser.add_argument("--reviewer", choices=tuple(REVIEWERS), default="sonnet")
    arguments = parser.parse_args()
    if arguments.step == "static":
        write_jsonl(candidates_path(arguments.set), _candidates_for(arguments.set))
        print(candidates_path(arguments.set))
        return
    if arguments.step == "review":
        target = verdicts_path(arguments.set, arguments.reviewer)
        write_jsonl(target, verdicts(read_jsonl(candidates_path(arguments.set)), arguments.reviewer))
        print(target)
        return
    report = {
        reviewer: {
            name: corpus_record(reviewer) if name == "corpus" else answer_record(name, reviewer)
            for name in SETS if verdicts_path(name, reviewer).exists()
        }
        for reviewer in REVIEWERS
    }
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
