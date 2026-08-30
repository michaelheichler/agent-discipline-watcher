"""One reader per sentence, because the candidate stage answers what is near, not what is true."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

try:
    from .judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
except ImportError:
    from judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt

try:
    from . import judge_provider
    from .judge import JUDGE_MODEL, JUDGE_TIMEOUT_SECONDS, available
    from .judge_provider import unavailable_reason
except ImportError:
    import judge_provider
    from judge import JUDGE_MODEL, JUDGE_TIMEOUT_SECONDS, available
    from judge_provider import unavailable_reason

VIOLATING = "violating"
CLEAN = "clean"
BATCH_SIZE = 20
# Haiku only, because a stronger agent must never run.
JUDGED_GATE_MODEL = JUDGE_MODEL
JUDGE_WORKERS = 8
JSON_ARRAY_RE = re.compile(r"\[.*]", re.DOTALL)
# Stable to keep the hour cache, a cent down to a fraction.
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


class JudgedOutcome(NamedTuple):
    """Split out, because one empty mapping meant both an unread rule and a cleared one."""

    kept: dict[str, tuple[PatternCandidate, ...]]
    unjudged: tuple[str, ...]
    reason: str


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


def _provider(model: str) -> judge_provider.Provider:
    return judge_provider.Provider(model, SYSTEM_PROMPT, JUDGE_TIMEOUT_SECONDS)


def _run(prompt: str, model: str) -> str | None:
    return judge_provider.complete(prompt, _provider(model)).text


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


def confirm(rule: PatternRule, candidates: tuple[PatternCandidate, ...], model: str) -> tuple[PatternCandidate, ...]:
    """Nothing survives an absent judge, because the candidate stage alone measured 0.62."""
    if not candidates or not available():
        return ()
    kept: list[PatternCandidate] = []
    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start : start + BATCH_SIZE]
        kept.extend(candidate for candidate, real in zip(batch, _batch_verdicts(rule, batch, model)) if real)
    return tuple(kept)


def confirm_all(work: tuple[tuple[PatternRule, tuple[PatternCandidate, ...]], ...], model: str) -> JudgedOutcome:
    """Judged in parallel because one call per rule ran 27 times in series and cost a file scan 228 seconds."""
    pending = tuple((rule, candidates) for rule, candidates in work if candidates)
    if not pending:
        return JudgedOutcome({}, (), "")
    reason = unavailable_reason()
    if reason:
        return JudgedOutcome({}, tuple(rule.name for rule, _candidates in pending), reason)
    with ThreadPoolExecutor(max_workers=min(JUDGE_WORKERS, len(pending))) as pool:
        answered = pool.map(lambda entry: confirm(entry[0], entry[1], model), pending)
    kept = {rule.name: found for (rule, _candidates), found in zip(pending, answered) if found}
    return JudgedOutcome(kept, (), "")
