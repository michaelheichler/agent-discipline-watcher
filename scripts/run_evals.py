#!/usr/bin/env python3
"""Kept as one CLI here because a maintainer running an eval always needs validate, run, and score to agree on the same case schema."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

from eval_scoring import CONDITIONS, summarize_scores


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "cases.jsonl"
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


def load_cases(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def _load_valid_cases(path: Path) -> list[dict[str, Any]]:
    cases = load_cases(path)
    errors = validate_cases(cases)
    if errors:
        raise ValueError("\n".join(errors))
    return cases


def completed_keys(rows: list[JsonRow]) -> set[RunKey]:
    keys: set[RunKey] = set()
    for row in rows:
        case_id = row.get("case_id")
        trial = row.get("trial")
        condition = row.get("condition")
        runner = row.get("runner")
        if (
            isinstance(case_id, str)
            and isinstance(trial, int)
            and isinstance(condition, str)
            and isinstance(runner, str)
        ):
            keys.add((case_id, trial, condition, runner))
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
    cases = _load_valid_cases(args.cases)
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
    for attempt in range(retries + 1):
        completed = subprocess.run(
            invocation,
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if completed.returncode == 0 or attempt == retries:
            return completed
        time.sleep(min(2**attempt, 5))
    raise RuntimeError("--retries must be zero or greater")


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
        except (ValueError, json.JSONDecodeError) as exc:
            detail = f"{detail}\n(response also failed to parse: {exc})"
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
    if args.retries < 0:
        raise ValueError("--retries must be zero or greater")
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


def _validate_command(args: argparse.Namespace) -> int:
    errors = validate_cases(load_cases(args.cases))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Evaluation cases are valid.")
    return 0


def _plan_command(args: argparse.Namespace) -> int:
    cases = _load_valid_cases(args.cases)
    conditions = ["baseline", "candidate"]
    if args.include_comparator:
        conditions.append("comparator")
    trials = range(1, args.trials + 1)
    for trial, case, condition in product(trials, cases, conditions):
        print(json.dumps({"case_id": case["id"], "trial": trial, "condition": condition}))
    return 0


def _score_command(args: argparse.Namespace) -> int:
    print(json.dumps(summarize_scores(read_jsonl(args.scores)), indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate the case catalog")
    validate.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    validate.set_defaults(handler=_validate_command)

    plan = subparsers.add_parser("plan", help="Print the paired run matrix as JSONL")
    plan.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    plan.add_argument("--trials", type=int, default=3)
    plan.add_argument("--include-comparator", action="store_true")
    plan.set_defaults(handler=_plan_command)

    score = subparsers.add_parser("score", help="Aggregate manually judged score rows")
    score.add_argument("scores", type=Path)
    score.set_defaults(handler=_score_command)

    _add_run_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
