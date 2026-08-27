#!/usr/bin/env python3
"""The regex and the reader are scored as one stage, because a rule at the judged gate reports nothing until the reader confirms it."""
import json
import sys
import time
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.config import DEFAULTS, JUDGED_STATE
from lib.pattern_judge import JUDGED_GATE_MODEL, PatternCandidate, confirm
from lib.pattern_semantic import load_exemplars, load_manifest, rule_prompt
from lib.scanner import scan_all

BENCHMARK_PATH = REPOSITORY_ROOT / "evals" / "benchmark_patterns.jsonl"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "regex_judge.json"
SAMPLE_NAME = "sample.md"
VIOLATING = "violating"
HELD_OUT = "held_out"


class Stage(NamedTuple):
    rule: str
    true_positive: int
    false_positive: int
    missed: int
    judged: int


def _judged_rules() -> tuple[str, ...]:
    gates = DEFAULTS["rule_gates"]
    return tuple(sorted(rule for rule, state in gates.items() if state == JUDGED_STATE))


def load_rows(rule: str) -> list[dict]:
    with BENCHMARK_PATH.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    return [row for row in rows if row["rule"] == rule and row["split"] == HELD_OUT]


def _fires(rule: str, text: str) -> bool:
    return any(finding["rule"] == rule for finding in scan_all(SAMPLE_NAME, text, {}))


def _flagged(rule: str, rows: list[dict]) -> list[dict]:
    return [row for row in rows if _fires(rule, row["text"])]


def _confirmed(rule: str, flagged: list[dict]) -> list[dict]:
    exemplars = load_exemplars()
    manifest = load_manifest()
    prompt = rule_prompt(rule, exemplars, manifest)
    candidates = tuple(PatternCandidate(SAMPLE_NAME, index, row["text"]) for index, row in enumerate(flagged))
    kept = {candidate.line for candidate in confirm(prompt, candidates, JUDGED_GATE_MODEL)}
    return [row for index, row in enumerate(flagged) if index in kept]


def measure(rule: str) -> Stage:
    rows = load_rows(rule)
    if not rows:
        raise ValueError(f"{rule}: the benchmark holds no held-out rows, rebuild it first")
    flagged = _flagged(rule, rows)
    confirmed = _confirmed(rule, flagged)
    true_positive = sum(row["label"] == VIOLATING for row in confirmed)
    violating_total = sum(row["label"] == VIOLATING for row in rows)
    return Stage(rule, true_positive, len(confirmed) - true_positive, violating_total - true_positive, len(flagged))


def _report(stage: Stage) -> dict[str, object]:
    reported = stage.true_positive + stage.false_positive
    found = stage.true_positive + stage.missed
    return {
        "model": JUDGED_GATE_MODEL,
        "regex_candidates": stage.judged,
        "confirmed": reported,
        "true_positive": stage.true_positive,
        "false_positive": stage.false_positive,
        "precision": round(stage.true_positive / reported, 4) if reported else 0.0,
        "recall": round(stage.true_positive / found, 4) if found else 0.0,
        "held_out_violating": found,
    }


def main() -> None:
    report = {}
    for rule in _judged_rules():
        print(f"{rule}: measuring", flush=True)
        stage = measure(rule)
        report[rule] = _report(stage)
        print(f"  {json.dumps(report[rule])}", flush=True)
        time.sleep(1.0)
    OUTPUT_PATH.write_text(
        json.dumps({"benchmark": BENCHMARK_PATH.name, "rules": report}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


if __name__ == "__main__":
    main()
