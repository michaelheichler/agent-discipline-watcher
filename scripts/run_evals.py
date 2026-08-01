#!/usr/bin/env python3
"""Validate, run, and score paired response-quality evaluations."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "cases.jsonl"
WEIGHTS = {
    "correctness": 0.35,
    "autonomy": 0.25,
    "actionability": 0.20,
    "safety": 0.10,
    "concision": 0.10,
}
CONDITIONS = {"baseline", "candidate", "comparator"}
JsonRow = dict[str, Any]
RunKey = tuple[str, int, str, str]
ParsedResponse = tuple[str, dict[str, Any], float | None]


@dataclass
class _EvaluationRun:
    args: argparse.Namespace
    cases: list[dict[str, Any]]
    runner: dict[str, Any]
    command: list[str]
    response_format: str
    done: set[tuple[str, int, str, str]]
    reported_cost: float


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {number}: expected a JSON object")
        rows.append(row)
    return rows


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    return read_jsonl(path)


def completed_keys(rows: list[JsonRow]) -> set[RunKey]:
    keys: set[RunKey] = set()
    for row in rows:
        fields = (row.get("case_id"), row.get("trial"), row.get("condition"), row.get("runner"))
        if isinstance(fields[0], str) and isinstance(fields[1], int) and all(
            isinstance(value, str) for value in fields[2:]
        ):
            keys.add(fields)  # type: ignore[arg-type]
    return keys


def _case_errors(
    case: dict[str, Any], index: int, seen: set[str]
) -> list[str]:
    required = {"id", "category", "prompt", "risk", "criteria"}
    missing = sorted(required - set(case))
    if missing:
        return [f"Case {index}: missing fields: {', '.join(missing)}"]
    errors: list[str] = []
    case_id = case["id"]
    if not isinstance(case_id, str) or not case_id:
        errors.append(f"Case {index}: id must be a non-empty string")
    elif case_id in seen:
        errors.append(f"Duplicate case id: {case_id}")
    else:
        seen.add(case_id)
    if case["risk"] not in {"low", "medium", "high"}:
        errors.append(f"Case {case_id}: risk must be low, medium, or high")
    if not isinstance(case["criteria"], list) or not case["criteria"]:
        errors.append(f"Case {case_id}: criteria must be a non-empty list")
    return errors


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        errors.extend(_case_errors(case, index, seen))
    return errors


def _validate_score(row: dict[str, Any], index: int) -> None:
    required = {"case_id", "trial", "condition", *WEIGHTS, "blocker", "notes"}
    missing = sorted(required - set(row))
    if missing:
        raise ValueError(f"Score row {index}: missing fields: {', '.join(missing)}")
    if row["condition"] not in CONDITIONS:
        raise ValueError(f"Score row {index}: unsupported condition {row['condition']!r}")
    for metric in WEIGHTS:
        value = row[metric]
        if not isinstance(value, (int, float)) or not 1 <= value <= 5:
            raise ValueError(f"Score row {index}: {metric} must be between 1 and 5")
    if not isinstance(row["blocker"], bool):
        raise ValueError(f"Score row {index}: blocker must be boolean")


def _describe_rows(keys: list[tuple[str, Any]]) -> str:
    return ", ".join(f"{case_id}/trial {trial}" for case_id, trial in keys)


def _score_coverage(
    grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, Counter[tuple[str, Any]]]:
    return {
        condition: Counter((row["case_id"], row["trial"]) for row in rows)
        for condition, rows in grouped.items()
    }


def _check_duplicate_scores(coverage: dict[str, Counter[tuple[str, Any]]]) -> None:
    for condition, counts in sorted(coverage.items()):
        repeated = sorted(key for key, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(
                f"{condition}: duplicate score rows for {_describe_rows(repeated)}"
            )


def _pairing_mismatch(
    baseline: Counter[tuple[str, Any]], counts: Counter[tuple[str, Any]]
) -> str:
    details = []
    missing = sorted(set(baseline) - set(counts))
    if missing:
        details.append(f"missing {_describe_rows(missing)}")
    unmatched = sorted(set(counts) - set(baseline))
    if unmatched:
        details.append(f"unmatched {_describe_rows(unmatched)}")
    return "; ".join(details)


def _check_pairing(grouped: dict[str, list[dict[str, Any]]]) -> None:
    coverage = _score_coverage(grouped)
    _check_duplicate_scores(coverage)
    baseline = coverage["baseline"]
    for condition, counts in sorted(coverage.items()):
        if condition == "baseline" or counts == baseline:
            continue
        raise ValueError(
            f"{condition} was not judged on the same rows as baseline: "
            + _pairing_mismatch(baseline, counts)
        )


def _summarize_condition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        metric: sum(float(row[metric]) for row in rows) / len(rows)
        for metric in WEIGHTS
    }
    return {
        "rows": len(rows),
        **metrics,
        "weighted_score": sum(metrics[metric] * weight for metric, weight in WEIGHTS.items()),
        "blocking_findings": sum(bool(row["blocker"]) for row in rows),
    }


def _release_gate_reasons(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> list[str]:
    reasons: list[str] = []
    if candidate["blocking_findings"]:
        reasons.append("Candidate has blocking safety or correctness findings.")
    if candidate["correctness"] < baseline["correctness"] - 0.1:
        reasons.append("Candidate correctness regressed by more than 0.1 points.")
    if candidate["safety"] < baseline["safety"] - 0.1:
        reasons.append("Candidate safety regressed by more than 0.1 points.")
    if candidate["weighted_score"] <= baseline["weighted_score"]:
        reasons.append("Candidate weighted score did not beat baseline.")
    return reasons


def summarize_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(scores, start=1):
        _validate_score(row, index)
        grouped[row["condition"]].append(row)
    if "baseline" not in grouped or "candidate" not in grouped:
        raise ValueError("Scores must include baseline and candidate conditions")
    _check_pairing(grouped)
    conditions = {
        condition: _summarize_condition(rows)
        for condition, rows in sorted(grouped.items())
    }
    reasons = _release_gate_reasons(conditions["baseline"], conditions["candidate"])
    return {
        "weights": WEIGHTS,
        "conditions": conditions,
        "release_gate": {"passed": not reasons, "reasons": reasons},
    }


def _condition_prompt(task: str, condition: str, skill_path: Path | None) -> str:
    if condition == "baseline":
        return task
    if skill_path is None:
        raise ValueError(f"--condition-skill is required for the {condition} condition")
    instructions = skill_path.read_text(encoding="utf-8")
    return (
        "Follow the response-style skill below while completing the task. "
        "Do not discuss or quote the skill.\n\n"
        f"<response_style>\n{instructions}\n</response_style>\n\n"
        f"<task>\n{task}\n</task>"
    )


def _parse_codex_response(output: str) -> ParsedResponse:
    events = [json.loads(line) for line in output.splitlines() if line.strip()]
    text = ""
    usage: dict[str, Any] = {}
    for event in events:
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text", text)
        if event.get("type") == "turn.completed":
            usage = event.get("usage", usage)
    return str(text).strip(), usage, None


def _parse_response(output: str, response_format: str) -> ParsedResponse:
    if response_format == "text":
        return output.strip(), {}, None
    if response_format == "claude-json":
        payload = json.loads(output)
        return (
            str(payload.get("result", "")).strip(),
            payload.get("usage", {}) or {},
            payload.get("total_cost_usd"),
        )
    if response_format == "codex-jsonl":
        return _parse_codex_response(output)
    raise ValueError(f"Unsupported response format: {response_format}")


def _validated_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    cases = load_cases(args.cases)
    errors = validate_cases(cases)
    if errors:
        raise ValueError("\n".join(errors))
    unknown = sorted(set(args.case or []) - {case["id"] for case in cases})
    if unknown:
        raise ValueError(f"--case matched no evaluation case: {', '.join(unknown)}")
    return cases


def _runner_settings(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[str], str]:
    config = json.loads(args.runner_config.read_text(encoding="utf-8"))
    runner = config[args.runner]
    response_format = runner.get("response_format", "text")
    if response_format != "claude-json" and not args.allow_unmetered:
        raise RuntimeError(
            f"The {response_format!r} response format never reports dollar cost; rerun with "
            "--allow-unmetered only when the provider has a separate hard spending cap."
        )
    return runner, list(runner["command"]), response_format


def _resume_state(args: argparse.Namespace) -> tuple[set[RunKey], float]:
    prior_rows = read_jsonl(args.output) if args.output.exists() else []
    reported_cost = sum(
        float(row.get("cost_usd") or 0)
        for row in prior_rows
        if row.get("condition") == args.condition and row.get("runner") == args.runner
    )
    return completed_keys(prior_rows), reported_cost


def _evaluation_run(args: argparse.Namespace) -> _EvaluationRun:
    cases = _validated_cases(args)
    runner, command, response_format = _runner_settings(args)
    done, reported_cost = _resume_state(args)
    return _EvaluationRun(
        args, cases, runner, command, response_format, done, reported_cost
    )


def _pending_runs(run: _EvaluationRun) -> Iterator[tuple[int, dict[str, Any]]]:
    trials = range(1, run.args.trials + 1)
    for trial, case in product(trials, run.cases):
        if run.args.case and case["id"] not in run.args.case:
            continue
        key = (case["id"], trial, run.args.condition, run.args.runner)
        if key in run.done:
            print(f"skip completed {run.args.condition} trial {trial}: {case['id']}")
            continue
        yield trial, case


def _build_invocation(run: _EvaluationRun, prompt: str, remaining: float) -> list[str]:
    invocation = [*run.command]
    if run.runner.get("budget_flag"):
        invocation.extend([run.runner["budget_flag"], f"{remaining:.4f}"])
    invocation.append(prompt)
    return invocation


def _run_command(invocation: list[str], retries: int) -> subprocess.CompletedProcess[str]:
    completed = None
    for attempt in range(retries + 1):
        completed = subprocess.run(
            invocation,
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if completed.returncode == 0:
            break
        if attempt < retries:
            time.sleep(min(2**attempt, 5))
    assert completed is not None
    return completed


def _raise_runner_error(
    completed: subprocess.CompletedProcess[str],
    invocation: list[str],
    run: _EvaluationRun,
) -> None:
    detail = completed.stderr.strip() or completed.stdout.strip()
    if completed.stdout.strip():
        try:
            parsed_text, _, _ = _parse_response(completed.stdout, run.response_format)
            detail = parsed_text or detail
        except (ValueError, json.JSONDecodeError):
            pass
    raise RuntimeError(
        f"Runner failed after {run.args.retries + 1} attempts "
        f"({shlex.join(invocation[:-1])}):\n{detail}"
    )


def _completed_response(
    completed: subprocess.CompletedProcess[str],
    invocation: list[str],
    run: _EvaluationRun,
) -> tuple[str, dict[str, Any], float | None]:
    if completed.returncode:
        _raise_runner_error(completed, invocation, run)
    text, usage, cost = _parse_response(completed.stdout, run.response_format)
    if cost is None and not run.args.allow_unmetered:
        raise RuntimeError(
            "Runner did not report dollar cost; rerun with --allow-unmetered only when "
            "the provider has a separate hard spending cap."
        )
    return text, usage, cost


def _evaluate_case(
    pending: tuple[int, dict[str, Any]], remaining: float, run: _EvaluationRun
) -> tuple[dict[str, Any], float]:
    trial, case = pending
    prompt = _condition_prompt(
        case["prompt"], run.args.condition, run.args.condition_skill
    )
    invocation = _build_invocation(run, prompt, remaining)
    completed = _run_command(invocation, run.args.retries)
    text, usage, cost = _completed_response(completed, invocation, run)
    row = {
        "case_id": case["id"],
        "trial": trial,
        "condition": run.args.condition,
        "runner": run.args.runner,
        "response": text,
        "usage": usage,
        "cost_usd": cost,
    }
    return row, float(cost or 0)


def _write_pending(destination: Any, run: _EvaluationRun) -> int:
    for pending in _pending_runs(run):
        trial, case = pending
        remaining = run.args.budget_usd - run.reported_cost
        if remaining <= 0:
            print("Budget exhausted; stopping.", file=sys.stderr)
            return 2
        row, cost = _evaluate_case(pending, remaining, run)
        run.reported_cost += cost
        destination.write(json.dumps(row, ensure_ascii=False) + "\n")
        destination.flush()
        print(f"{run.args.condition} trial {trial}: {case['id']}")
    return 0


def _write_evaluations(run: _EvaluationRun) -> int:
    with run.args.output.open("a", encoding="utf-8") as destination:
        status = _write_pending(destination, run)
    if status:
        return status
    print(f"Reported cost: ${run.reported_cost:.4f}")
    return 0


def run_evaluations(args: argparse.Namespace) -> int:
    run = _evaluation_run(args)
    if args.budget_usd <= 0 or args.budget_usd > 25:
        raise ValueError("--budget-usd must be greater than 0 and no more than 25")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    return _write_evaluations(run)


def _add_run_parser(subparsers: Any) -> None:
    run = subparsers.add_parser("run", help="Run one evaluation condition")
    run.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    run.add_argument("--runner-config", type=Path, default=ROOT / "evals" / "runners.example.json")
    run.add_argument("--runner", required=True)
    run.add_argument("--condition", choices=sorted(CONDITIONS), required=True)
    run.add_argument(
        "--condition-skill",
        type=Path,
        default=ROOT / "skills" / "readable-output" / "SKILL.md",
    )
    run.add_argument("--case", action="append")
    run.add_argument("--trials", type=int, default=3)
    run.add_argument("--retries", type=int, default=2)
    run.add_argument("--budget-usd", type=float, default=25.0)
    run.add_argument("--allow-unmetered", action="store_true")
    run.add_argument("--output", type=Path, required=True)
    run.set_defaults(handler=run_evaluations)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Validate the case catalog")
    validate.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    plan = subparsers.add_parser("plan", help="Print the paired run matrix as JSONL")
    plan.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    plan.add_argument("--trials", type=int, default=3)
    plan.add_argument("--include-comparator", action="store_true")
    score = subparsers.add_parser("score", help="Aggregate manually judged score rows")
    score.add_argument("scores", type=Path)
    _add_run_parser(subparsers)
    return parser


def _validate_command(args: argparse.Namespace) -> int:
    errors = validate_cases(load_cases(args.cases))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Evaluation cases are valid.")
    return 0


def _plan_command(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    errors = validate_cases(cases)
    if errors:
        raise ValueError("\n".join(errors))
    conditions = ["baseline", "candidate"]
    if args.include_comparator:
        conditions.append("comparator")
    trials = range(1, args.trials + 1)
    for trial, case, condition in product(trials, cases, conditions):
        print(json.dumps({"case_id": case["id"], "trial": trial, "condition": condition}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "handler"):
        return args.handler(args)
    if args.command == "validate":
        return _validate_command(args)
    if args.command == "plan":
        return _plan_command(args)
    if args.command == "score":
        print(json.dumps(summarize_scores(read_jsonl(args.scores)), indent=2))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
