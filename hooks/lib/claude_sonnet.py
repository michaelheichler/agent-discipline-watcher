"""Stop review on Sonnet through the Claude CLI, because an agent hook cannot run the journal helper."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from . import claude_luna
from .claude_presets import CLAUDE_SONNET_MODEL
from .hookio import read_payload, stop_block, system_message, write_payload
from .judge_contracts import DOCUMENT_SCHEMA, PATTERN_SCHEMA, JudgeResult, ReviewKind, build_prompt, validate_payload
from .judge_provider import RECURSION_GUARD
from .luna_feedback import bounded
from .luna_validation import validate_candidate_indexes

REVIEWER = "Sonnet"
CLI_TIMEOUT_SECONDS = 90
EXEC_PATH_ENV = "CLAUDE_CODE_EXECPATH"
NO_HOOKS_SETTINGS = '{"disableAllHooks":true}'
NO_MCP_CONFIG = '{"mcpServers":{}}'
SYSTEM_PROMPT = (
    "You review one finished turn for reader-facing English. The user message holds numbered sections.\n"
    "A pattern section names one rule, the fix it asks for, real examples of both sides, and numbered "
    "candidate sentences. A document section holds the hunks the agent changed this turn, each labelled "
    "with its line range. A line that starts with + changed this turn.\n"
    "Answer every candidate of every pattern section with one item. Set section to the section number "
    "and index to the candidate number inside that section. Judge each candidate against that section's rule alone.\n"
    "For document sections, judge only the changed lines. Use the other lines only to understand them, "
    "and never flag them. Add one note per problem a reader can check against the text, six at most. "
    "Quote the sentence exactly, without its leading marker. Return no notes when the documents are fine.\n"
    "Answer from the message alone. You have no tools and never open a file. When uncertain, answer clean."
)
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


def batch_prompt(work: list[claude_luna.Work]) -> str:
    return "\n\n".join(
        f"Section {number} ({request.review_kind.value}).\n{build_prompt(request)}"
        for number, (request, _sources) in enumerate(work)
    )


def claude_command() -> list[str]:
    """No hooks and no tools, because a nested call that fired ADW hooks would review its own review."""
    binary = shutil.which("claude") or os.environ.get(EXEC_PATH_ENV, "")
    if not binary:
        raise ReviewUnavailable("the claude CLI is not on PATH")
    return [
        binary, "-p", "--model", CLAUDE_SONNET_MODEL, "--output-format", "json",
        "--json-schema", json.dumps(BATCH_SCHEMA, separators=(",", ":")),
        "--tools", "", "--no-session-persistence", "--settings", NO_HOOKS_SETTINGS,
        "--strict-mcp-config", "--mcp-config", NO_MCP_CONFIG, "--disable-slash-commands",
        "--system-prompt", SYSTEM_PROMPT,
    ]


def _claude_judge(prompt: str) -> str:
    """Because argv would show source text in the process list, stdin carries the prompt."""
    try:
        done = subprocess.run(
            claude_command(), input=prompt, capture_output=True, text=True, check=False,
            timeout=CLI_TIMEOUT_SECONDS, cwd=tempfile.gettempdir(), env={**os.environ, RECURSION_GUARD: "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ReviewUnavailable(f"the claude CLI timed out after {CLI_TIMEOUT_SECONDS} seconds") from exc
    except OSError as exc:
        raise ReviewUnavailable(f"the claude CLI could not start: {exc}") from exc
    if not done.stdout.strip():
        raise ReviewUnavailable(f"the claude CLI exited {done.returncode} with no output: {bounded(done.stderr)}")
    return done.stdout


def batch_payload(stdout: str) -> dict[str, Any]:
    try:
        body = json.loads(stdout)
    except ValueError as exc:
        raise ReviewUnavailable("the claude CLI printed no JSON") from exc
    if not isinstance(body, dict) or body.get("is_error"):
        detail = body.get("result") if isinstance(body, dict) else body
        raise ReviewUnavailable(f"the claude CLI reported an error: {bounded(detail)}")
    try:
        return validate_payload(body.get("structured_output"), BATCH_SCHEMA)
    except ValueError as exc:
        raise ReviewUnavailable(f"the verdict did not match the schema: {exc}") from exc


def _result(payload: dict[str, Any]) -> JudgeResult:
    return JudgeResult(payload, "claude", CLAUDE_SONNET_MODEL, "", "adw-batch-v1", {})


def _pattern_result(request: Any, items: list[dict[str, Any]]) -> JudgeResult:
    ordered = sorted(({key: item[key] for key in _VERDICT["required"]} for item in items), key=lambda item: item["index"])
    payload = {"items": ordered}
    try:
        validate_candidate_indexes(request, payload)
    except ValueError as exc:
        raise ReviewUnavailable("the verdict skipped or repeated a candidate") from exc
    return _result(payload)


def verdict_texts(work: list[claude_luna.Work], payload: dict[str, Any]) -> list[str]:
    """Slice the batch per request, because the Luna wording code reads one request at a time."""
    answered: dict[int, list[dict[str, Any]]] = {}
    for item in payload["items"]:
        answered.setdefault(item["section"], []).append(item)
    pattern_sections = {number for number, (request, _s) in enumerate(work) if request.review_kind is ReviewKind.PATTERN}
    if set(answered) - pattern_sections:
        raise ReviewUnavailable("the verdict named a section that holds no pattern")
    texts = [
        claude_luna.feedback(request, _pattern_result(request, answered.get(number, [])), sources, REVIEWER)
        for number, (request, sources) in enumerate(work)
        if number in pattern_sections
    ]
    documents = [(request, sources) for request, sources in work if request.review_kind is ReviewKind.DOCUMENT]
    if documents:
        rows = [row for _request, sources in documents for row in sources]
        texts.append(claude_luna.feedback(documents[0][0], _result({"notes": payload["notes"]}), rows, REVIEWER))
    return [text for text in texts if text]


def _unavailable(reason: str) -> dict:
    return system_message(bounded(f"ADW {REVIEWER} review did not run this turn: {reason}. Its findings stay queued."))


def _is_stop(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("hook_event_name") == "Stop"


def run(payload: object, *, state_root: str | os.PathLike[str] | None = None, judge: Judge = _claude_judge) -> dict:
    """Empty turns exit before the call, because a model call with nothing to judge only costs tokens."""
    if os.environ.get(RECURSION_GUARD, "").strip() or not _is_stop(payload):
        return {}
    config = claude_luna.hook_config(payload)
    root = state_root if state_root is not None else config.get("state_root")
    rows = claude_luna.stop_rows(payload, root)
    work = claude_luna.stop_work(rows, config) if rows else None
    try:
        texts = verdict_texts(work, batch_payload(judge(batch_prompt(work)))) if work else []
    except ReviewUnavailable as exc:
        return _unavailable(str(exc))
    claude_luna.mark_reviewed(payload, rows, root)
    return stop_block("\n\n".join(texts)) if texts else {}


def main() -> int:
    write_payload(run(read_payload()))
    return 0
