"""Runs on the Claude Code session login rather than an API key, because a hook must not spend a key the user did not choose to spend here."""
from __future__ import annotations

import json
import os
import re
from typing import NamedTuple

try:
    from .judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
except ImportError:
    from judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt

JUDGE_MODEL = "claude-haiku-4-5"
JUDGE_TIMEOUT_SECONDS = 120
RECURSION_GUARD = "ADW_JUDGE_ACTIVE"
# WHY: A named verdict rather than a boolean, because the model inverted a "narrates" flag while its own reason named the narration.
DESCRIBES_CODE = "describes_code"
STATES_WHY = "states_why"
# WHY: A stable system prompt keeps the 15k prefix in the one hour cache, which is the difference between 0.034 and 0.006 per call.
JUDGE_SYSTEM_PROMPT = (
    "You judge one Python comment or docstring line at a time against a single rule.\n"
    "A line may state why the code is the way it is. A line may not describe what the code does.\n"
    "The opening clause decides it. If its subject is the code and its verb names the behaviour, "
    "the line describes the code and fails, and a trailing because clause does not rescue it. "
    "If the opening clause names a decision, a constraint, a measurement, or a consequence, it passes.\n"
    "describes_code: 'Returns the rows because the caller needs a stable order.'\n"
    "describes_code: 'Blocks the payload, because an interpreter reaches write APIs the scanner cannot read.'\n"
    "describes_code: 'Sweeps as it reads, because a crashed session would pin the model forever.'\n"
    "states_why: 'Set to 1.5 because Tukey fence lands at 36.5 words on 5000 sentences.'\n"
    "states_why: 'Kept out of the blocking path because a gate that waits stalls every write.'\n"
    "states_why: 'Resolved, because os.replace on a symlink destroys the link instead of its target.'\n"
    "Reply with a JSON array and nothing else. One object per numbered item, in order: "
    '{"index": <number>, "verdict": "describes_code" or "states_why", "reason": "<at most 12 words>"}.'
)
JSON_ARRAY_RE = re.compile(r"\[.*]", re.DOTALL)


class Candidate(NamedTuple):
    path: str
    line: int
    text: str


class Verdict(NamedTuple):
    candidate: Candidate
    narrates: bool
    reason: str


def available() -> bool:
    return not os.environ.get(RECURSION_GUARD, "").strip()


def _environment() -> dict[str, str]:
    """Drops the API key because the session login is the account the user already pays for, and keeps the guard so a nested hook cannot recurse."""
    env = {key: value for key, value in os.environ.items() if key != "ANTHROPIC_API_KEY"}
    env[RECURSION_GUARD] = "1"
    return env


def request_for(candidates: tuple[Candidate, ...]) -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind.COMMENT,
        candidates=tuple(candidate.text for candidate in candidates),
    )


def build_prompt(candidates: tuple[Candidate, ...]) -> str:
    return build_judge_prompt(request_for(candidates))


def _run(prompt: str) -> str | None:
    return None


def _result_text(raw: str) -> str:
    body = json.loads(raw)
    if not isinstance(body, dict) or body.get("is_error") or not isinstance(body.get("result"), str):
        raise ValueError(f"judge returned no usable result: {raw[:200]!r}")
    return body["result"]


def parse_verdicts(text: str, candidates: tuple[Candidate, ...]) -> tuple[Verdict, ...]:
    match = JSON_ARRAY_RE.search(text)
    if match is None:
        raise ValueError(f"judge answered without a JSON array: {text[:200]!r}")
    rows = json.loads(match.group(0))
    return tuple(
        Verdict(
            candidates[row["index"]],
            row.get("verdict") == DESCRIBES_CODE,
            str(row.get("reason", "")),
        )
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("index"), int)
        and 0 <= row["index"] < len(candidates)
        and row.get("verdict") in (DESCRIBES_CODE, STATES_WHY)
    )


def judge(candidates: tuple[Candidate, ...]) -> tuple[Verdict, ...] | None:
    if not candidates:
        return ()
    if not available():
        return None
    raw = _run(build_prompt(candidates))
    if raw is None:
        return None
    return parse_verdicts(_result_text(raw), candidates)
