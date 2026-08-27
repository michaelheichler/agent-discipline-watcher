"""A line rule cannot see an argument that arrives in the wrong order, because every regex here reads one sentence at a time."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from typing import NamedTuple

try:
    from .judge import JSON_ARRAY_RE, JUDGE_TIMEOUT_SECONDS, _environment, available
except ImportError:
    from judge import JSON_ARRAY_RE, JUDGE_TIMEOUT_SECONDS, _environment, available

REVIEW_MODEL = "claude-sonnet-5"
MAX_REVIEW_CHARS = 24000
MAX_NOTES = 6
MAX_REVIEW_ROUNDS = 2
STATE_KEY = "document_review"
BLOCKER_KEY_PREFIX = "<document-review>:"
WHITESPACE_RE = re.compile(r"\s+")
# WHY: A stable prompt keeps the prefix cached, and naming the two axes stops the model from grading the subject matter.
SYSTEM_PROMPT = (
    "You review one finished document for coherence and style.\n"
    "Name only problems a reader can check against the text you were given.\n"
    "Never score the document, never say whether a model wrote it, and never judge whether its claims are true.\n"
    "Coherence: an order that hides the argument, a missing bridge between paragraphs, "
    "a referent used before it is introduced, a claim the document later contradicts.\n"
    "Style: a paragraph shape repeated until it reads as a tic, a register that shifts without reason, "
    "a sentence whose subordination buries its subject, a stock opener or closer.\n"
    "Quote the sentence you mean, exactly as it appears.\n"
    "Reply with a JSON array and nothing else, at most six objects, most serious first: "
    '[{"quote": "<exact sentence>", "problem": "<at most 20 words>", "fix": "<at most 20 words>"}].\n'
    "Reply with [] when the document carries none of these."
)


class Note(NamedTuple):
    line: int
    quote: str
    problem: str
    fix: str


def _command() -> list[str]:
    return [
        "claude", "-p",
        "--model", REVIEW_MODEL,
        "--output-format", "json",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt", SYSTEM_PROMPT,
    ]


def _run(prompt: str) -> str | None:
    try:
        finished = subprocess.run(
            [*_command(), prompt], capture_output=True, text=True, check=False,
            timeout=JUDGE_TIMEOUT_SECONDS, env=_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return finished.stdout if finished.returncode == 0 else None


def _line_of(text: str, quote: str) -> int:
    """A quote is anchored by search rather than by index because the model rewrites whitespace when it copies a sentence."""
    needle = WHITESPACE_RE.sub(" ", quote).strip()
    if not needle:
        return 0
    for number, line in enumerate(text.splitlines(), 1):
        if needle[:60] in WHITESPACE_RE.sub(" ", line):
            return number
    return 0


def parse_notes(raw: str, text: str) -> tuple[Note, ...]:
    body = json.loads(raw)
    if not isinstance(body, dict) or body.get("is_error") or not isinstance(body.get("result"), str):
        raise ValueError(f"the reviewer returned no usable result: {raw[:200]!r}")
    found = JSON_ARRAY_RE.search(body["result"])
    if found is None:
        raise ValueError(f"the reviewer answered without a JSON array: {body['result'][:160]!r}")
    rows = json.loads(found.group(0))
    return tuple(
        Note(_line_of(text, str(row.get("quote", ""))), str(row.get("quote", "")),
             str(row.get("problem", "")), str(row.get("fix", "")))
        for row in rows[:MAX_NOTES]
        if isinstance(row, dict) and row.get("problem")
    )


def build_prompt(path: str, text: str) -> str:
    return f"Document: {path}\n\n{text[:MAX_REVIEW_CHARS]}"


def review(path: str, text: str) -> tuple[Note, ...]:
    """An absent reviewer names nothing, because a document that was never read must not report as coherent."""
    if not text.strip() or not available():
        return ()
    raw = _run(build_prompt(path, text))
    if raw is None:
        return ()
    try:
        return parse_notes(raw, text)
    except (ValueError, TypeError):
        return ()


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def previous(state: dict, path: str) -> tuple[str, int]:
    rows = state.get(STATE_KEY)
    row = rows.get(path) if isinstance(rows, dict) else None
    if not isinstance(row, dict):
        return "", 0
    rounds = row.get("rounds")
    return str(row.get("digest", "")), rounds if isinstance(rounds, int) else 0


def remember(state: dict, path: str, digest: str, rounds: int) -> dict:
    rows = state.get(STATE_KEY)
    rows = dict(rows) if isinstance(rows, dict) else {}
    rows[path] = {"digest": digest, "rounds": rounds}
    return {**state, STATE_KEY: rows}


def message(path: str, notes: tuple[Note, ...]) -> str:
    lines = [f"agent-discipline-watcher read {path} whole and found these before you stop:"]
    lines.extend(f"  {path}:{note.line}: {note.problem} Fix: {note.fix}" for note in notes)
    lines.append("Fix them, or say why they stand, then stop again.")
    return "\n".join(lines)
