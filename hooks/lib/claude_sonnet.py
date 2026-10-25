"""Stop review on Sonnet through the Claude CLI, because an agent hook cannot run the journal helper."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple

from . import claude_luna, journal, payloads, reporting, turn_retry
from .claude_presets import CLAUDE_SONNET_MODEL
from .document_review import HUNK_NOTICE
from .hookio import advise, read_payload, system_message, write_payload
from .judge_contracts import (
    DOCUMENT_RUBRIC, DOCUMENT_SCHEMA, GERMAN_PATTERN_RUBRIC, PATTERN_RUBRIC, PATTERN_SCHEMA,
    JudgeResult, ReviewKind, build_prompt, reviewer_instructions, validate_payload,
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
PARATAXIS_SKIPPED = "skipped a parataxis run, which needs its own answer, so the run stays queued for the next Stop."
LEDGER_HOOK = "claude_sonnet"
DROPPED_RULE = "review_dropped"
MAX_NAMED_ROWS = 5
SYSTEM_PROMPT = (
    "You review one finished turn for reader-facing English. The user message holds numbered sections.\n"
    "A pattern section names one rule, the fix it asks for, real examples of both sides, and numbered "
    "candidate sentences. A document section holds the hunks the agent changed this turn, each labelled "
    "with its line range. A line that starts with + changed this turn.\n"
    "For each pattern candidate, set section to the section number and index to the candidate number "
    "inside that section. Judge each candidate against that section's rule alone.\n"
    f"{PATTERN_RUBRIC}\n"
    "For document sections, judge only the changed lines. Use the other lines only to understand them, "
    f"and never flag them. {DOCUMENT_RUBRIC} Leave out the leading marker when you quote. Add one note per problem."
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
    ledger_root: str | Path | None = None


class Verdicts(NamedTuple):
    texts: list[claude_luna.Answer]
    skipped: list[dict[str, Any]]
    judged: tuple[claude_luna.Judged, ...] = ()


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


def system_prompt(config: dict) -> str:
    return f"{SYSTEM_PROMPT}\n{reviewer_instructions(config)}"


def claude_command(system: str) -> list[str]:
    """No hooks, tools, or setting sources, because a nested call that loaded them would review its own review."""
    binary = shutil.which("claude") or os.environ.get(EXEC_PATH_ENV, "")
    if not binary:
        raise CliUnavailable("the claude CLI is not on PATH")
    return [
        binary, "-p", "--model", CLAUDE_SONNET_MODEL, "--output-format", "json",
        "--json-schema", json.dumps(BATCH_SCHEMA, separators=(",", ":")),
        "--tools", "", "--no-session-persistence", "--setting-sources", "", "--settings", NO_HOOKS_SETTINGS,
        "--strict-mcp-config", "--mcp-config", NO_MCP_CONFIG, "--disable-slash-commands",
        "--system-prompt", system,
    ]


def _claude_judge(prompt: str, system: str) -> str:
    """Because argv would show source text in the process list, stdin carries the prompt."""
    env = {**os.environ, RECURSION_GUARD: "1", NO_AUTO_MEMORY_ENV: "1"}
    try:
        done = subprocess.run(
            claude_command(system), input=prompt, capture_output=True, text=True, check=False,
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


def _pattern_result(request: Any, items: list[dict[str, Any]]) -> tuple[JudgeResult, list[int]]:
    """Because one slip must not void every verdict, a gap stays queued and a repeat keeps its first answer."""
    count = len(request.candidates)
    chosen: dict[int, dict[str, Any]] = {}
    for item in items:
        if 0 <= item["index"] < count:
            chosen.setdefault(item["index"], {key: item[key] for key in _VERDICT["required"]})
    skipped = [index for index in range(count) if index not in chosen]
    clean = {"verdict": "clean", "reason": MISSING_VERDICT_REASON}
    return _result({"items": [chosen.get(index, {"index": index, **clean}) for index in range(count)]}), skipped


def verdict_texts(work: list[claude_luna.Work], payload: dict[str, Any]) -> Verdicts:
    """Slice the batch per request, because the Luna wording code reads one request at a time."""
    pattern_sections = {number for number, (request, _s) in enumerate(work) if request.review_kind is ReviewKind.PATTERN}
    answered: dict[int, list[dict[str, Any]]] = {}
    for item in payload["items"]:
        if item["section"] in pattern_sections:
            answered.setdefault(item["section"], []).append(item)
    judged, skipped = _pattern_answers(work, pattern_sections, answered)
    texts: list[claude_luna.Answer] = [(request, text) for request, text, _rows in judged]
    documents = [(request, sources) for request, sources in work if request.review_kind is ReviewKind.DOCUMENT]
    if documents:
        rows = [row for _request, sources in documents for row in sources]
        note = claude_luna.feedback(documents[0][0], _result({"notes": payload["notes"]}), rows, REVIEWER)
        texts.append((documents[0][0], note))
    return Verdicts([(request, text) for request, text in texts if text], skipped, tuple(judged))


def _pattern_answers(
    work: list[claude_luna.Work], sections: set[int], answered: dict[int, list[dict[str, Any]]],
) -> tuple[list[claude_luna.Judged], list[dict[str, Any]]]:
    judged: list[claude_luna.Judged] = []
    skipped: list[dict[str, Any]] = []
    for number, (request, sources) in enumerate(work):
        if number not in sections:
            continue
        result, gaps = _pattern_result(request, answered.get(number, []))
        skipped.extend(sources[index] for index in gaps)
        judged.append((request, claude_luna.feedback(request, result, sources, REVIEWER), claude_luna.violating_rows(request, result, sources)))
    return judged, skipped


def _row_names(rows: list[dict[str, Any]]) -> str:
    names = []
    for row in rows:
        name = Path(str(row.get("path") or "")).name or "an unnamed file"
        line = row.get("line")
        names.append(f"{name}:{line}" if row.get("role") == "pattern" and type(line) is int else name)
    unique = list(dict.fromkeys(names))
    shown = ", ".join(unique[:MAX_NAMED_ROWS])
    return f"{shown} and {len(unique) - MAX_NAMED_ROWS} more" if len(unique) > MAX_NAMED_ROWS else shown


def _dropped_text(dropped: list[dict[str, Any]]) -> str:
    return (
        f"It dropped {len(dropped)} queued findings unreviewed after {turn_retry.MAX_REVIEW_ATTEMPTS} "
        f"attempts without a verdict: {_row_names(dropped)}."
    )


def _record_dropped(stop: StopContext, dropped: list[dict[str, Any]]) -> None:
    for row in dropped:
        reporting.record_decision(
            session_id=stop.session_id, hook=LEDGER_HOOK, event="Stop", family="", rule=DROPPED_RULE,
            path=str(row.get("path") or ""), tool_use_id="", outcome="release", duration_ms=0,
            turn_id=str(row.get("turn_id") or ""), root=stop.ledger_root,
        )


def _exhausted(stop: StopContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Counted per row, so a row that never gets a verdict stops resending."""
    try:
        keys = [journal._reviewed_key(row) for row in rows]
        exhausted = turn_retry.exhausted_reviews(stop.session_id, keys, stop.root)
    except (OSError, ValueError, TypeError):
        return []
    dropped = [row for row in rows if journal._reviewed_key(row) in exhausted]
    if dropped:
        claude_luna.mark_reviewed(stop.payload, dropped, stop.root)
        _record_dropped(stop, dropped)
    return dropped


def _unavailable(reason: str, dropped: list[dict[str, Any]], queued: int) -> dict:
    lead = f"ADW {REVIEWER} review did not run this turn: {reason}."
    if not dropped:
        return system_message(bounded(f"{lead} Its findings stay queued."))
    rest = " The rest stay queued." if len(dropped) < queued else ""
    return advise(bounded(f"{lead} {_dropped_text(dropped)}{rest}"), "Stop")


def _failed(stop: StopContext, rows: list[dict[str, Any]], error: ReviewUnavailable) -> dict:
    try:
        if isinstance(error, CliUnavailable):
            turn_retry.record_cli_outage(stop.session_id, str(error), stop.root)
    except (OSError, ValueError, TypeError):
        return _unavailable(str(error), [], len(rows))
    return _unavailable(str(error), _exhausted(stop, rows), len(rows))


def _cooldown_notice(stop: StopContext) -> dict:
    """Visible, because a silent cooldown reads like a clean review."""
    try:
        cooldown = turn_retry.cli_cooldown(stop.session_id, stop.root)
    except (OSError, ValueError, TypeError):
        return {}
    if cooldown is None:
        return {}
    reason, retry_after = cooldown
    until = time.strftime("%H:%M:%S", time.localtime(retry_after))
    return system_message(bounded(
        f"ADW {REVIEWER} review did not run this turn: {reason or 'the claude CLI failed'}. "
        f"ADW skips the CLI until {until}, and the queued findings stay queued."
    ))


def _answered(rows: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Held back by key, because the reviewed mark is what keeps a skipped candidate queued."""
    held = {journal._reviewed_key(row) for row in skipped}
    return [row for row in rows if journal._reviewed_key(row) not in held]


def _with_notice(response: dict, text: str) -> dict:
    """Joined, because one hook reply carries one message per channel."""
    if not text:
        return response
    if response.get("decision") == "block":
        return {**response, "reason": f"{response.get('reason', '')}\n\n{text}"}
    earlier = response.get("hookSpecificOutput", {}).get("additionalContext", "")
    return advise("\n\n".join(part for part in (earlier, text) if part), "Stop")


def _retryable(stop: StopContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        counts = turn_retry.attempts(stop.session_id, stop.root)
    except (OSError, ValueError, TypeError):
        return rows
    return [row for row in rows if counts.get(journal._reviewed_key(row), 0) < turn_retry.MAX_REVIEW_ATTEMPTS]


def _is_stop(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("hook_event_name") == "Stop"


def run(payload: object, *, state_root: str | Path | None = None, judge: Judge | None = None) -> dict:
    """Upheld blocks are read first, because the verdicts of this Stop join them only after the reply is built."""
    if os.environ.get(RECURSION_GUARD, "").strip() or not _is_stop(payload):
        return {}
    config = claude_luna.hook_config(payload)
    root = state_root if state_root is not None else config.get("state_root")
    stop = StopContext(payloads.session_id(payload), payload, root, config.get("ledger_root"))
    held = claude_luna.held_blocks(payload, stop.root, config)
    return claude_luna.keep_held(_review(stop, config, judge), held)


def _review(stop: StopContext, config: dict, judge: Judge | None) -> dict:
    """Empty turns exit before the call, because a model call with nothing to judge only costs tokens."""
    queued = claude_luna.stop_rows(stop.payload, stop.root)
    if not queued:
        return {}
    cooling = _cooldown_notice(stop)
    if cooling:
        return cooling
    rows = _retryable(stop, queued)
    if not rows:
        return {}
    work = claude_luna.stop_work(rows, config)
    ask = judge or partial(_claude_judge, system=system_prompt(config))
    try:
        verdicts = verdict_texts(work, batch_payload(ask(batch_prompt(work)))) if work else Verdicts([], [])
    except ReviewUnavailable as exc:
        return _failed(stop, rows, exc)
    claude_luna.mark_reviewed(stop.payload, _answered(rows, verdicts.skipped), stop.root)
    claude_luna.remember_blocks(stop.payload, list(verdicts.judged), config, stop.root)
    dropped = _exhausted(stop, verdicts.skipped) if verdicts.skipped else []
    response = claude_luna.stop_verdict(verdicts.texts, config)
    return _with_notice(response, _skip_notice(verdicts.skipped, dropped))


def _skip_notice(skipped: list[dict[str, Any]], dropped: list[dict[str, Any]]) -> str:
    """Because each parataxis run needs its own answer, a silent gap would read as a clean run."""
    waiting = any(row.get("rule") in PARATAXIS_RULES for row in skipped if row not in dropped)
    if not waiting and not dropped:
        return ""
    tail = f" {_dropped_text(dropped)}" if dropped else ""
    return bounded(f"ADW {REVIEWER} review {PARATAXIS_SKIPPED if waiting else 'skipped candidates.'}{tail}")


def main() -> int:
    write_payload(run(read_payload()))
    return 0
