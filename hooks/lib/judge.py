"""One judge call on the session login, because a hook must not spend a key nobody chose."""
from __future__ import annotations

import json
import re
from typing import NamedTuple

try:
    from . import judge_provider
    from .judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
    from .judge_model import DEFAULT_JUDGE_MODEL, judge_model
except ImportError:
    import judge_provider
    from judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
    from judge_model import DEFAULT_JUDGE_MODEL, judge_model

JUDGE_MODEL = DEFAULT_JUDGE_MODEL
JUDGE_TIMEOUT_SECONDS = 120
RECURSION_GUARD = judge_provider.RECURSION_GUARD
# Named because the model inverted its own boolean.
DESCRIBES_CODE = "describes_code"
STATES_WHY = "states_why"
# Stable to keep the hour cache, 0.034 down to 0.006 a call.
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
    """Ask the provider because host policy decides this, not a raw environment read."""
    return judge_provider.available()


def _environment() -> dict[str, str]:
    """Kept as the name three callers already import, because the provider owns the real build."""
    return judge_provider.child_environment()


def request_for(candidates: tuple[Candidate, ...]) -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind.COMMENT,
        candidates=tuple(candidate.text for candidate in candidates),
    )


def build_prompt(candidates: tuple[Candidate, ...]) -> str:
    return build_judge_prompt(request_for(candidates))


def _provider(model: str = JUDGE_MODEL) -> judge_provider.Provider:
    return judge_provider.Provider(model, JUDGE_SYSTEM_PROMPT, JUDGE_TIMEOUT_SECONDS)


def _run(prompt: str, model: str = JUDGE_MODEL) -> str | None:
    return judge_provider.complete(prompt, _provider(model)).text


def _result_text(raw: str) -> str:
    body = json.loads(raw)
    if not isinstance(body, dict) or body.get("is_error") or not isinstance(body.get("result"), str):
        raise ValueError(f"judge returned no usable result: {raw[:200]!r}")
    return body["result"]


def parse_verdicts(text: str, candidates: tuple[Candidate, ...]) -> tuple[Verdict, ...]:
    """Require one valid verdict per candidate, because omission must never silently clear a finding."""
    match = JSON_ARRAY_RE.search(text)
    if match is None:
        raise ValueError(f"judge answered without a JSON array: {text[:200]!r}")
    rows = json.loads(match.group(0))
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise ValueError("judge must answer every candidate exactly once")
    parsed: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("index")) is not int or row["index"] in parsed:  # pylint: disable=unidiomatic-typecheck
            raise ValueError("judge returned duplicate or invalid candidate indexes")
        if not 0 <= row["index"] < len(candidates):
            raise ValueError("judge returned an out-of-range candidate index")
        if row.get("verdict") not in (DESCRIBES_CODE, STATES_WHY):
            raise ValueError("judge returned an invalid verdict")
        parsed[row["index"]] = row
    if set(parsed) != set(range(len(candidates))):
        raise ValueError("judge must answer every candidate exactly once")
    return tuple(
        Verdict(candidates[index], parsed[index]["verdict"] == DESCRIBES_CODE, str(parsed[index].get("reason", "")))
        for index in range(len(candidates))
    )


def judge(candidates: tuple[Candidate, ...], model: str | None = None) -> tuple[Verdict, ...] | None:
    """Screen the selection first because only a haiku agent may reach the provider."""
    if not candidates:
        return ()
    if not available():
        return None
    selected = judge_model(model)
    raw = _run(build_prompt(candidates), selected)
    if raw is None:
        return None
    return parse_verdicts(_result_text(raw), candidates)
