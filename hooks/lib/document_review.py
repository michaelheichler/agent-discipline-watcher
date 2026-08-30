"""A line rule cannot see an argument that arrives in the wrong order, because every regex here reads one sentence at a time."""
from __future__ import annotations

import hashlib
import json
import re
from typing import NamedTuple

try:
    from .judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
except ImportError:
    from judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt

try:
    from . import judge_provider
    from .judge import JSON_ARRAY_RE, JUDGE_TIMEOUT_SECONDS, available
except ImportError:
    import judge_provider
    from judge import JSON_ARRAY_RE, JUDGE_TIMEOUT_SECONDS, available

try:
    from .reporting import _safe_text
    from .judge import JUDGE_MODEL
except ImportError:
    from reporting import _safe_text
    from judge import JUDGE_MODEL

REVIEW_MODEL = JUDGE_MODEL
MAX_REVIEW_CHARS = 24000
MAX_NOTES = 6
MAX_REVIEW_ROUNDS = 2
STATE_KEY = "document_review"
BLOCKER_KEY_PREFIX = "<document-review>:"
WHITESPACE_RE = re.compile(r"\s+")
# Two named axes to prevent the model grading subject matter.
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


def _provider(model: str = REVIEW_MODEL) -> judge_provider.Provider:
    return judge_provider.Provider(model, SYSTEM_PROMPT, JUDGE_TIMEOUT_SECONDS)


def _run(prompt: str, model: str = REVIEW_MODEL) -> str | None:
    return judge_provider.complete(prompt, _provider(model)).text


def _line_of(text: str, quote: str) -> int:
    """Search rather than index, because the model rewrites whitespace when it copies a sentence."""
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


def request_for(path: str, text: str) -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind.DOCUMENT,
        source_context=f"Document: {path}\n\n{text[:MAX_REVIEW_CHARS]}",
    )

def build_prompt(path: str, text: str) -> str:
    return build_judge_prompt(request_for(path, text))

def review(path: str, text: str, config: dict | None = None) -> tuple[Note, ...]:
    """No model review without a data boundary, because source text would leave the machine."""
    if config is None:
        return ()
    boundary = config.get("data_boundary")
    if not isinstance(boundary, dict) or boundary.get("enabled") is not True:
        return ()
    if not text.strip() or not available():
        return ()
    model = str(config.get("adw_model") or REVIEW_MODEL)
    raw = _run(build_prompt(path, text), model)
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
    safe_path = _safe_text(path).replace("\n", " ")
    lines = [f"agent-discipline-watcher read {safe_path} whole and found these before you stop:"]
    lines.extend(
        f"  {safe_path}:{note.line}: {_safe_text(note.problem)} Fix: {_safe_text(note.fix)}"
        for note in notes
    )
    lines.append("Fix them, or say why they stand, then stop again.")
    return "\n".join(lines)
