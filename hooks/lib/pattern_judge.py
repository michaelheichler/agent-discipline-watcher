"""Decides one named pattern per sentence, because the candidate stage answers what is near and only a reader answers what is true."""
from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

try:
    from .judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
except ImportError:
    from judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt

try:
    from .judge import JUDGE_TIMEOUT_SECONDS, _environment, available
except ImportError:
    from judge import JUDGE_TIMEOUT_SECONDS, _environment, available

VIOLATING = "violating"
CLEAN = "clean"
BATCH_SIZE = 20
# WHY: A rule at the judged gate reports on its reader alone, so it is worth a stronger one than the batched sentence pass.
JUDGED_GATE_MODEL = "claude-sonnet-5"
JUDGE_WORKERS = 8
JSON_ARRAY_RE = re.compile(r"\[.*]", re.DOTALL)
# WHY: A stable system prompt keeps the prefix in the one hour cache, which is the difference between a cent and a fraction of one.
SYSTEM_PROMPT = (
    "You decide whether one sentence instantiates one named writing pattern.\n"
    "You are given the pattern name, the fix the pattern asks for, and real examples of both sides.\n"
    "Judge only the named pattern. A sentence may be poor for other reasons and still not instantiate this one.\n"
    "Reply with a JSON array and nothing else. One object per numbered item, in order: "
    '{"index": <number>, "verdict": "violating" or "clean"}.'
)


class PatternCandidate(NamedTuple):
    path: str
    line: int
    text: str


class PatternRule(NamedTuple):
    name: str
    action: str
    violating_examples: tuple[str, ...]
    clean_examples: tuple[str, ...]


def request_for(rule: PatternRule, candidates: tuple[PatternCandidate, ...]) -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind.PATTERN,
        candidates=tuple(candidate.text for candidate in candidates),
        rule_name=rule.name,
        rule_action=rule.action,
        violating_examples=rule.violating_examples,
        clean_examples=rule.clean_examples,
    )


def build_prompt(rule: PatternRule, candidates: tuple[PatternCandidate, ...]) -> str:
    return build_judge_prompt(request_for(rule, candidates))


def _command(model: str) -> list[str]:
    return [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--tools", "",
        "--system-prompt", SYSTEM_PROMPT,
    ]


def _run(prompt: str, model: str) -> str | None:
    try:
        finished = subprocess.run(
            [*_command(model), prompt],
            capture_output=True, text=True, check=False,
            timeout=JUDGE_TIMEOUT_SECONDS, env=_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return finished.stdout if finished.returncode == 0 else None


def parse_verdicts(raw: str, size: int) -> tuple[bool, ...]:
    """Require one valid verdict per candidate, because omission must never silently clear a finding."""
    body = json.loads(raw)
    if not isinstance(body, dict) or body.get("is_error") or not isinstance(body.get("result"), str):
        raise ValueError(f"the judge returned no usable result: {raw[:200]!r}")
    found = JSON_ARRAY_RE.search(body["result"])
    if found is None:
        raise ValueError(f"the judge answered without a JSON array: {body['result'][:160]!r}")
    rows = json.loads(found.group(0))
    if not isinstance(rows, list) or len(rows) != size:
        raise ValueError("the judge must answer every candidate exactly once")
    parsed: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("index"), int) or row["index"] in parsed:
            raise ValueError("the judge returned duplicate or invalid candidate indexes")
        verdict = row.get("verdict")
        if verdict not in (VIOLATING, CLEAN):
            raise ValueError("the judge returned an invalid verdict")
        parsed[row["index"]] = verdict
    if set(parsed) != set(range(size)):
        raise ValueError("the judge must answer every candidate exactly once")
    return tuple(parsed[index] == VIOLATING for index in range(size))


def _batch_verdicts(rule: PatternRule, batch: tuple[PatternCandidate, ...], model: str) -> tuple[bool, ...]:
    raw = _run(build_prompt(rule, batch), model)
    return parse_verdicts(raw, len(batch)) if raw is not None else (False,) * len(batch)


def confirm(
    rule: PatternRule, candidates: tuple[PatternCandidate, ...], model: str
) -> tuple[PatternCandidate, ...]:
    """An absent judge confirms nothing, because a candidate stage alone was measured at 0.62 precision on one rule."""
    if not candidates or not available():
        return ()
    kept: list[PatternCandidate] = []
    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start : start + BATCH_SIZE]
        kept.extend(candidate for candidate, real in zip(batch, _batch_verdicts(rule, batch, model)) if real)
    return tuple(kept)


def confirm_all(
    work: tuple[tuple[PatternRule, tuple[PatternCandidate, ...]], ...], model: str
) -> dict[str, tuple[PatternCandidate, ...]]:
    """Judged in parallel because one call per rule ran 27 times in series and cost a file scan 228 seconds."""
    pending = tuple((rule, candidates) for rule, candidates in work if candidates)
    if not pending or not available():
        return {}
    with ThreadPoolExecutor(max_workers=min(JUDGE_WORKERS, len(pending))) as pool:
        answered = pool.map(lambda entry: confirm(entry[0], entry[1], model), pending)
    return {rule.name: kept for (rule, _candidates), kept in zip(pending, answered) if kept}
