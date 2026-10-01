#!/usr/bin/env python3
"""Score the German trigger and the Luna judge as one stage, because a German rule reports nothing until the judge confirms a trigger match."""
import argparse
import functools
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

from ai_corpus_de import ADJUDICATED_PATH, REPOSITORY_ROOT, ai_corpus_digest, load_ai_corpus, load_labels

OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "judge_stage_de.json"
BATCH = 20
WILSON_Z = 1.96
ENFORCE_LOWER_BOUND = 0.85
SAMPLE_NAME = "sample.md"
VIOLATING = "violating"
DECIDED = (VIOLATING, "clean")
Judge = Callable[[Any], Any]


class Row(NamedTuple):
    line: int
    text: str
    violating: bool


@functools.cache
def _hook() -> SimpleNamespace:
    """Imported from the hook, because a measurement of another prompt would gate a judge nobody runs."""
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    from lib import pattern_judge, pattern_semantic
    return SimpleNamespace(
        exemplars=pattern_semantic.load_exemplars(), manifest=pattern_semantic.load_manifest(),
        rule_prompt=pattern_semantic.rule_prompt, rule_trigger=pattern_semantic.rule_trigger,
        candidate=pattern_judge.PatternCandidate, request_for=pattern_judge.request_for,
    )


def wilson_lower(successes: int, total: int, z: float = WILSON_Z) -> float:
    """Lower bound, because 9 of 9 confirmed says less than 90 of 100 and the gate must see that."""
    if total == 0:
        return 0.0
    share = successes / total
    centre = share + z * z / (2 * total)
    spread = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total))
    return round((centre - spread) / (1 + z * z / total), 4)


def score(rows: list[Row], verdicts: list[bool]) -> dict[str, object]:
    confirmed = [row for row, verdict in zip(rows, verdicts) if verdict]
    true_positive = sum(row.violating for row in confirmed)
    violating = sum(row.violating for row in rows)
    return {
        "candidates": len(rows), "violating": violating, "confirmed": len(confirmed), "true_positive": true_positive,
        "precision": round(true_positive / len(confirmed), 4) if confirmed else None,
        "precision_lower_bound": wilson_lower(true_positive, len(confirmed)),
        "recall": round(true_positive / violating, 4) if violating else None,
    }


def _verdicts(result: Any, size: int) -> list[bool]:
    found = {row["index"]: row["verdict"] == VIOLATING for row in result.payload["items"]}
    if set(found) != set(range(size)):
        raise ValueError("the judge must answer every candidate exactly once")
    return [found[index] for index in range(size)]


def judged(rule: str, rows: list[Row], judge: Judge) -> list[bool]:
    hook = _hook()
    prompt = hook.rule_prompt(rule, hook.exemplars, hook.manifest)
    verdicts: list[bool] = []
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        candidates = tuple(hook.candidate(SAMPLE_NAME, row.line, row.text) for row in batch)
        verdicts.extend(_verdicts(judge(hook.request_for(prompt, candidates)), len(batch)))
    return verdicts


def rule_rows(rule: str, labels: list[dict], texts: dict[int, str]) -> list[Row]:
    return [
        Row(label["line"], texts[label["line"]], label["label"] == VIOLATING)
        for label in labels if label["rule"] == rule and label["label"] in DECIDED
    ]


def recommendation(lower_bound: float) -> str:
    return "enforce" if lower_bound >= ENFORCE_LOWER_BOUND else "observe"


def measure(rule: str, rows: list[Row], judge: Judge) -> dict[str, object]:
    """Exemplars held out, because the judge reads those sentences as examples and would score them for free."""
    shown = {row.text for row in _hook().exemplars if row.rule == rule}
    models: set[str] = set()

    def recorded(request: Any) -> Any:
        result = judge(request)
        models.add(str(getattr(result, "model", "")))
        return result

    verdicts = judged(rule, rows, recorded)
    held = [(row, verdict) for row, verdict in zip(rows, verdicts) if row.text not in shown]
    after = score([row for row, _ in held], [verdict for _, verdict in held])
    return {
        "after_judge": after, "all_candidates": score(rows, verdicts), "models": sorted(models),
        "confirmed_lines": [row.line for row, verdict in zip(rows, verdicts) if verdict],
        "recommendation": recommendation(float(after["precision_lower_bound"])),
    }


def triggered_rules() -> list[str]:
    """Only rules the hook would send, because a silent rule has no stage to measure."""
    hook = _hook()
    return sorted(
        rule for rule in hook.manifest["rules"]
        if hook.rule_trigger(hook.manifest, rule) is not None
        and any(row.rule == rule and row.label == VIOLATING for row in hook.exemplars)
    )


class ModelMismatch(RuntimeError):
    """Raised, because verdicts from another Luna under this model key would mix two judges in one table."""


def pinned(judge: Judge, model: str) -> Judge:
    """Checked per request, because the resolver may move to another Luna mid-run."""
    def checked(request: Any) -> Any:
        result = judge(request)
        resolved = str(getattr(result, "model", ""))
        print(f"  {len(request.candidates)} candidates resolved {resolved}", flush=True)
        if resolved != model:
            raise ModelMismatch(f"expected {model}, resolved {resolved}")
        return result
    return checked


def newest_run(measured: dict[str, dict]) -> dict[str, dict]:
    """The highest Luna, because the hook resolves the highest Luna the SDK lists."""
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    from lib.luna_validation import parse_luna_version
    return measured[max(measured, key=lambda model: parse_luna_version(model) or ())]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="the Luna id every request must resolve")
    parser.add_argument("--scratch", type=Path, help="throwaway runtime and cache roots, so a newer SDK runs outside ~/.adw")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    ai_corpus_digest()
    texts = {row.line: row.text for row in load_ai_corpus()}
    labels = load_labels(ADJUDICATED_PATH)
    rules = triggered_rules()
    from lib.luna_provider import LunaJudge
    roots = {"runtime_root": arguments.scratch / "runtime", "cache_root": arguments.scratch / "cache"} if arguments.scratch else {}
    judge = pinned(LunaJudge(**roots).judge, arguments.model)
    report = {}
    for rule in rules:
        print(f"{rule}: judging", flush=True)
        report[rule] = {"judge": "luna", **measure(rule, rule_rows(rule, labels, texts), judge)}
        print(f"  {json.dumps(report[rule]['after_judge'])}", flush=True)
    runs = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.is_file() else {}
    runs[arguments.model] = report
    OUTPUT_PATH.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
