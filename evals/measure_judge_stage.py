#!/usr/bin/env python3
"""Measures the judge behind the candidate stage, because recall without a second opinion only moves the false positives downstream."""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

# pylint: disable=wrong-import-position
from lib.judge import JUDGE_MODEL, JUDGE_TIMEOUT_SECONDS, _environment
from lib.scanner import ENGLISH_RULES

sys.path.insert(0, str(REPOSITORY_ROOT / "evals"))
from qualify_embeddings import _similarity, embed_all

BENCHMARK_PATH = REPOSITORY_ROOT / "evals" / "benchmark_patterns.jsonl"
QUALIFICATION_PATH = REPOSITORY_ROOT / "evals" / "qualification.json"
OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "judge_stage.json"
EXAMPLES_PER_SIDE = 4
BATCH_SIZE = 20
RULES_MEASURED = 5
# WHY: Every flagged row is judged, because truncating the list drops true positives out of the recall denominator.
MAX_CANDIDATES = 400
RETRY_DELAYS = (5.0, 20.0, 60.0)
VIOLATING = "violating"
JSON_ARRAY_RE = re.compile(r"\[.*]", re.DOTALL)
SYSTEM_PROMPT = (
    "You decide whether one sentence instantiates one named writing pattern.\n"
    "You are given the pattern name, the fix the pattern asks for, and real examples of both sides.\n"
    "Judge only the named pattern. A sentence may be poor for other reasons and still not instantiate this one.\n"
    "Reply with a JSON array and nothing else. One object per numbered item, in order: "
    '{"index": <number>, "verdict": "violating" or "clean"}.'
)


class Stage(NamedTuple):
    rule: str
    true_positive: int
    false_positive: int
    missed: int


def rule_detail(rule: str) -> str:
    details = [detail for _pattern, name, detail in ENGLISH_RULES if name == rule]
    return details[0] if details else "Rewrite the line."


def load_rows() -> list[dict]:
    with BENCHMARK_PATH.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _examples(rows: list[dict], label: str) -> list[str]:
    return [row["text"] for row in rows if row["split"] == "development" and row["label"] == label][:EXAMPLES_PER_SIDE]


def build_prompt(rule: str, rows: list[dict], batch: list[dict]) -> str:
    violating = "\n".join(f"  violating: {text}" for text in _examples(rows, VIOLATING))
    clean = "\n".join(f"  clean: {text}" for text in _examples(rows, "clean"))
    items = "\n".join(f"{index}. {row['text']}" for index, row in enumerate(batch))
    return (
        f"Pattern: {rule}\nFix it asks for: {rule_detail(rule)}\n"
        f"Real examples:\n{violating}\n{clean}\n\nJudge each sentence.\n{items}"
    )


def _once(prompt: str) -> tuple[str | None, str]:
    command = [
        "claude", "-p", "--model", JUDGE_MODEL, "--output-format", "json",
        "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
        "--no-session-persistence", "--system-prompt", SYSTEM_PROMPT, prompt,
    ]
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, check=False,
            timeout=JUDGE_TIMEOUT_SECONDS, env=_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if finished.returncode != 0:
        return None, f"exit {finished.returncode}: {finished.stderr.strip()[:200]}"
    return finished.stdout, ""


def _run(prompt: str) -> str:
    """Retries because the session login rate limits a burst, and names the last error rather than scoring a silent gap as clean."""
    failure = ""
    for delay in RETRY_DELAYS:
        answered, failure = _once(prompt)
        if answered is not None:
            return answered
        print(f"  judge retry after {failure}", flush=True)
        time.sleep(delay)
    raise ValueError(f"the judge never answered: {failure}")


def _verdicts(raw: str, size: int) -> list[str]:
    body = json.loads(raw)
    found = JSON_ARRAY_RE.search(body["result"])
    if found is None:
        raise ValueError(f"the judge answered without a JSON array: {body['result'][:160]!r}")
    parsed = {int(row["index"]): str(row["verdict"]) for row in json.loads(found.group(0))}
    return [parsed.get(index, "clean") for index in range(size)]


def judge_rule(rule: str, rows: list[dict], candidates: list[dict]) -> list[str]:
    verdicts: list[str] = []
    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start : start + BATCH_SIZE]
        verdicts.extend(_verdicts(_run(build_prompt(rule, rows, batch)), len(batch)))
        print(f"  {rule}: judged {len(verdicts)} of {len(candidates)}", flush=True)
    return verdicts


def score(rule: str, candidates: list[dict], verdicts: list[str], missed: int) -> Stage:
    tally = Counter(
        (row["label"] == VIOLATING, verdict == VIOLATING)
        for row, verdict in zip(candidates, verdicts)
    )
    return Stage(rule, tally[(True, True)], tally[(False, True)], missed + tally[(True, False)])


def _stage_record(stage: Stage) -> dict[str, object]:
    kept = stage.true_positive + stage.false_positive
    actual = stage.true_positive + stage.missed
    return {
        "precision": round(stage.true_positive / kept, 4) if kept else None,
        "recall": round(stage.true_positive / actual, 4) if actual else None,
        "kept": kept,
        "held_out_violating": actual,
    }


def flagged(rule_rows: list[dict], vectors: dict, neighbours: int) -> tuple[list[dict], int]:
    development = [(row["label"], vectors[row["text"]]) for row in rule_rows if row["split"] == "development"]
    held_out = [row for row in rule_rows if row["split"] == "held_out"]
    kept = [
        row for row in held_out
        if Counter(
            name for name, _ in sorted(development, key=lambda entry: -_similarity(vectors[row["text"]], entry[1]))
        [:neighbours]).most_common(1)[0][0] == VIOLATING
    ]
    missed = sum(row["label"] == VIOLATING for row in held_out) - sum(row["label"] == VIOLATING for row in kept)
    return kept, missed


def _chosen_rules(report: dict) -> list[tuple[str, int]]:
    ranked = sorted(report["rules"].items(), key=lambda entry: -(entry[1]["recall"] or 0))
    return [(rule, row["neighbours"]) for rule, row in ranked[:RULES_MEASURED]]


def _measure(rule: str, neighbours: int, rows: list[dict], vectors: dict) -> Stage:
    rule_rows = [row for row in rows if row["rule"] == rule]
    candidates, missed = flagged(rule_rows, vectors, neighbours)
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError(f"{rule}: {len(candidates)} candidates exceed the {MAX_CANDIDATES} the run judges")
    return score(rule, candidates, judge_rule(rule, rule_rows, candidates), missed)


def _print_table(results: dict) -> None:
    print(f"{'rule':<24} {'recall before':>13} {'precision before':>17} {'precision after':>16} {'recall after':>13}")
    for rule, row in results.items():
        before, after = row["candidate_stage"], row["after_judge"]
        print(
            f"{rule:<24} {before['recall']:>13.4f} {before['precision']:>17.4f} "
            f"{after['precision']:>16.4f} {after['recall']:>13.4f}"
        )


def main() -> None:
    rows = load_rows()
    report = json.loads(QUALIFICATION_PATH.read_text(encoding="utf-8"))
    chosen = _chosen_rules(report)
    wanted = tuple(sorted({row["text"] for row in rows if row["rule"] in {name for name, _ in chosen}}))
    vectors = embed_all(wanted)
    results = {
        rule: {
            "candidate_stage": {key: report["rules"][rule][key] for key in ("recall", "precision", "flagged")},
            "after_judge": _stage_record(_measure(rule, neighbours, rows, vectors)),
        }
        for rule, neighbours in chosen
    }
    OUTPUT_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    _print_table(results)


if __name__ == "__main__":
    main()
