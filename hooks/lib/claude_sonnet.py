"""Stop review on Sonnet through the Claude CLI, because an agent hook cannot run the journal helper."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from . import claude_luna, journal, payloads, turn_retry
from .claude_presets import CLAUDE_SONNET_MODEL
from .document_review import HUNK_NOTICE
from .hookio import read_payload, system_message, write_payload
from .judge_contracts import (
    DOCUMENT_RUBRIC, DOCUMENT_SCHEMA, GERMAN_PATTERN_RUBRIC, PATTERN_RUBRIC, PATTERN_SCHEMA,
    JudgeResult, ReviewKind, build_prompt, validate_payload,
)
from .judge_provider import RECURSION_GUARD
from .luna_feedback import bounded
from .parataxis_lexicon import RULES as PARATAXIS_RULES

REVIEWER = "Sonnet"
CLI_TIMEOUT_SECONDS = 90
EXEC_PATH_ENV = "CLAUDE_CODE_EXECPATH"
NO_AUTO_MEMORY_ENV = "CLAUDE_CODE_DISABLE_AUTO_MEMORY"
NO_HOOKS_SETTINGS = '{"disableAllHooks":true}'
NO_MCP_CONFIG = '{"mcpServers":{}}'
MISSING_VERDICT_REASON = "The reviewer gave no verdict for this candidate."
SYSTEM_PROMPT = (
    "You review one finished turn for reader-facing English. The user message holds numbered sections.\n"
    "A pattern section names one rule, the fix it asks for, real examples of both sides, and numbered "
    "candidate sentences. A document section holds the hunks the agent changed this turn, each labelled "
    "with its line range. A line that starts with + changed this turn.\n"
    "Answer every candidate of every pattern section with one item. Set section to the section number "
    "and index to the candidate number inside that section. Judge each candidate against that section's rule alone.\n"
    f"{PATTERN_RUBRIC} A section in German holds German sentences, so measure them against German style, not English.\n"
    "For document sections, judge only the changed lines. Use the other lines only to understand them, "
    f"and never flag them. {DOCUMENT_RUBRIC} Leave out the leading marker when you quote. "
    "Add one note per problem a reader can check against the text, six at most. "
    "Return no notes when the documents are fine.\n"
    "Answer from the message alone. You have no tools and never open a file. When uncertain, answer clean."
)
_SECTION_RUBRICS = (f"{PATTERN_RUBRIC}\n", f"{GERMAN_PATTERN_RUBRIC}\n", f"{DOCUMENT_RUBRIC}\n\nDocument:\n")
_VERDICT = PATTERN_SCHEMA["properties"]["items"]["items"]
BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items", "notes"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                **_VERDICT,
                "required": ["section", *_VERDICT["required"]],
                "properties": {"section": {"type": "integer"}, **_VERDICT["properties"]},
            },
        },
        "notes": DOCUMENT_SCHEMA["properties"]["notes"],
    },
}
Judge = Callable[[str], str]


class ReviewUnavailable(Exception):
    """Raised when the model gave no usable verdict, so the review must say it did not run."""


class CliUnavailable(ReviewUnavailable):
    """Kept apart, because a CLI that failed once is cooled down instead of called on every Stop."""


class StopContext(NamedTuple):
    session_id: str
    payload: object
    root: str | Path | None


def section_body(request: Any) -> str:
    """Because the system prompt states every rubric once, a section carries only its rule and its text."""
    text = build_prompt(request)
    for rubric in _SECTION_RUBRICS:
        text = text.removeprefix(rubric)
    return text.replace(f"{HUNK_NOTICE}\n\n", "", 1)


def batch_prompt(work: list[claude_luna.Work]) -> str:
    return "\n\n".join(
        f"Section {number} ({request.review_kind.value}).\n{section_body(request)}"
        for number, (request, _sources) in enumerate(work)
    )


def claude_command() -> list[str]:
    """No hooks, tools, or setting sources, because a nested call that loaded them would review its own review."""
    binary = shutil.which("claude") or os.environ.get(EXEC_PATH_ENV, "")
    if not binary:
        raise CliUnavailable("the claude CLI is not on PATH")
    return [
        binary, "-p", "--model", CLAUDE_SONNET_MODEL, "--output-format", "json",
        "--json-schema", json.dumps(BATCH_SCHEMA, separators=(",", ":")),
        "--tools", "", "--no-session-persistence", "--setting-sources", "", "--settings", NO_HOOKS_SETTINGS,
        "--strict-mcp-config", "--mcp-config", NO_MCP_CONFIG, "--disable-slash-commands",
        "--system-prompt", SYSTEM_PROMPT,
    ]


def _claude_judge(prompt: str) -> str:
    """Because argv would show source text in the process list, stdin carries the prompt."""
    env = {**os.environ, RECURSION_GUARD: "1", NO_AUTO_MEMORY_ENV: "1"}
    try:
        done = subprocess.run(
            claude_command(), input=prompt, capture_output=True, text=True, check=False,
            timeout=CLI_TIMEOUT_SECONDS, cwd=tempfile.gettempdir(), env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise CliUnavailable(f"the claude CLI timed out after {CLI_TIMEOUT_SECONDS} seconds") from exc
    except OSError as exc:
        raise CliUnavailable(f"the claude CLI could not start: {exc}") from exc
    if not done.stdout.strip():
        raise CliUnavailable(f"the claude CLI exited {done.returncode} with no output: {bounded(done.stderr)}")
    return done.stdout


def batch_payload(stdout: str) -> dict[str, Any]:
    try:
        body = json.loads(stdout)
    except ValueError as exc:
        raise CliUnavailable("the claude CLI printed no JSON") from exc
    if not isinstance(body, dict) or body.get("is_error"):
        detail = body.get("result") if isinstance(body, dict) else body
        raise CliUnavailable(f"the claude CLI reported an error: {bounded(detail)}")
    try:
        return validate_payload(body.get("structured_output"), BATCH_SCHEMA)
    except ValueError as exc:
        raise ReviewUnavailable(f"the verdict did not match the schema: {exc}") from exc


def _result(payload: dict[str, Any]) -> JudgeResult:
    return JudgeResult(payload, "claude", CLAUDE_SONNET_MODEL, "", "adw-batch-v1", {})


def _pattern_result(request: Any, items: list[dict[str, Any]]) -> JudgeResult:
    """Because one slip must not void every verdict, a gap reads as clean and a repeat keeps its first answer."""
    count = len(request.candidates)
    chosen: dict[int, dict[str, Any]] = {}
    for item in items:
        index = item["index"]
        if type(index) is not int or not 0 <= index < count:
            raise ReviewUnavailable("the verdict named a candidate that does not exist")
        chosen.setdefault(index, {key: item[key] for key in _VERDICT["required"]})
    if request.rule_name in PARATAXIS_RULES and len(chosen) < count:
        raise ReviewUnavailable("the verdict skipped a parataxis run, which needs its own answer")
    clean = {"verdict": "clean", "reason": MISSING_VERDICT_REASON}
    return _result({"items": [chosen.get(index, {"index": index, **clean}) for index in range(count)]})


def verdict_texts(work: list[claude_luna.Work], payload: dict[str, Any]) -> list[claude_luna.Answer]:
    """Slice the batch per request, because the Luna wording code reads one request at a time."""
    answered: dict[int, list[dict[str, Any]]] = {}
    for item in payload["items"]:
        answered.setdefault(item["section"], []).append(item)
    pattern_sections = {number for number, (request, _s) in enumerate(work) if request.review_kind is ReviewKind.PATTERN}
    if set(answered) - pattern_sections:
        raise ReviewUnavailable("the verdict named a section that holds no pattern")
    texts = [
        (request, claude_luna.feedback(request, _pattern_result(request, answered.get(number, [])), sources, REVIEWER))
        for number, (request, sources) in enumerate(work)
        if number in pattern_sections
    ]
    documents = [(request, sources) for request, sources in work if request.review_kind is ReviewKind.DOCUMENT]
    if documents:
        rows = [row for _request, sources in documents for row in sources]
        note = claude_luna.feedback(documents[0][0], _result({"notes": payload["notes"]}), rows, REVIEWER)
        texts.append((documents[0][0], note))
    return [(request, text) for request, text in texts if text]


def _unavailable(reason: str, dropped: int, queued: int) -> dict:
    if not dropped:
        tail = "Its findings stay queued."
    else:
        rest = ", the rest stay queued" if dropped < queued else ""
        tail = f"It dropped {dropped} queued findings after {turn_retry.MAX_REVIEW_ATTEMPTS} failed attempts{rest}."
    return system_message(bounded(f"ADW {REVIEWER} review did not run this turn: {reason}. {tail}"))


def _failed(stop: StopContext, rows: list[dict[str, Any]], error: ReviewUnavailable) -> dict:
    dropped: list[dict[str, Any]] = []
    try:
        if isinstance(error, CliUnavailable):
            turn_retry.record_cli_outage(stop.session_id, str(error), stop.root)
        keys = [journal._reviewed_key(row) for row in rows]
        exhausted = turn_retry.exhausted_reviews(stop.session_id, keys, stop.root)
        dropped = [row for row in rows if journal._reviewed_key(row) in exhausted]
    except (OSError, ValueError, TypeError):
        dropped = []
    if dropped:
        claude_luna.mark_reviewed(stop.payload, dropped, stop.root)
    return _unavailable(str(error), len(dropped), len(rows))


def _retryable(stop: StopContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Empty while the CLI cools down, because a Stop in that window would only wait out the same failure."""
    try:
        if turn_retry.provider_cooling(stop.session_id, stop.root, turn_retry.CLI_OUTAGE_KEY):
            return []
        counts = turn_retry.attempts(stop.session_id, stop.root)
    except (OSError, ValueError, TypeError):
        return rows
    return [row for row in rows if counts.get(journal._reviewed_key(row), 0) < turn_retry.MAX_REVIEW_ATTEMPTS]


def _is_stop(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("hook_event_name") == "Stop"


def run(payload: object, *, state_root: str | Path | None = None, judge: Judge = _claude_judge) -> dict:
    """Empty turns exit before the call, because a model call with nothing to judge only costs tokens."""
    if os.environ.get(RECURSION_GUARD, "").strip() or not _is_stop(payload):
        return {}
    config = claude_luna.hook_config(payload)
    stop = StopContext(payloads.session_id(payload), payload, state_root if state_root is not None else config.get("state_root"))
    queued = claude_luna.stop_rows(payload, stop.root)
    rows = _retryable(stop, queued) if queued else []
    if not rows:
        return {}
    work = claude_luna.stop_work(rows, config)
    try:
        texts = verdict_texts(work, batch_payload(judge(batch_prompt(work)))) if work else []
    except ReviewUnavailable as exc:
        return _failed(stop, rows, exc)
    claude_luna.mark_reviewed(payload, rows, stop.root)
    return claude_luna.stop_verdict(texts, config)


def main() -> int:
    write_payload(run(read_payload()))
    return 0
