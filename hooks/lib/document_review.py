"""A line rule cannot see an argument that arrives in the wrong order, because every regex here reads one sentence at a time."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, NamedTuple

try:
    from .judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt
except ImportError:
    from judge_contracts import JudgeRequest, ReviewKind, build_prompt as build_judge_prompt

try:
    from . import judge_provider
    from .judge import JSON_ARRAY_RE, JUDGE_MODEL, JUDGE_TIMEOUT_SECONDS, available
except ImportError:
    import judge_provider
    from judge import JSON_ARRAY_RE, JUDGE_MODEL, JUDGE_TIMEOUT_SECONDS, available

try:
    from .reporting import _safe_text
except ImportError:
    from reporting import _safe_text

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


def _document_entries(rows: list[dict[str, Any]], content_limit: int) -> list[tuple[str, dict]]:
    entries = []
    for row in rows:
        if row.get("role") != "document" or not row.get("path") or not row.get("source_context"):
            continue
        path = str(row.get("path", ""))[:512]
        source = str(row.get("source_context", ""))
        if not source.strip():
            continue
        prefix = f"Path: {path}\n\n"[:max(0, content_limit - 1)]
        body_limit = max(1, content_limit - len(prefix))
        contexts = (prefix + source[offset:offset + body_limit] for offset in range(0, len(source), body_limit))
        entries.extend((context, row) for context in contexts if context.strip())
    return entries


def _pack_document_entries(entries: list[tuple[str, dict]], content_limit: int) -> list[tuple[str, list[dict]]]:
    packed = []
    current = ""
    sources: list[dict] = []
    for entry, row in entries:
        if current and len(current) + 2 + len(entry) > content_limit:
            packed.append((current, sources))
            current, sources = "", []
        current = entry if not current else f"{current}\n\n{entry}"
        if row not in sources:
            sources.append(row)
    if current:
        packed.append((current, sources))
    return packed


def document_work(rows: list[dict[str, Any]], maximum: int, label: str) -> list[tuple[JudgeRequest, list[Any]]]:
    """Split across requests, because a cut document reads as reviewed."""
    limit = max(1, maximum)
    header = f"Document: {label}\n\n"
    use_document_request = len(header) < limit
    content_limit = limit - len(header) if use_document_request else limit
    contexts = _pack_document_entries(_document_entries(rows, content_limit), content_limit)
    return [
        (
            request_for(label, context) if use_document_request
            else JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context=context),
            sources,
        )
        for context, sources in contexts
    ]


def data_boundary_enabled(cfg: dict) -> bool:
    """Exact True only, because source text leaves the machine."""
    boundary = cfg.get("data_boundary")
    return isinstance(boundary, dict) and boundary.get("enabled") is True


def build_prompt(path: str, text: str) -> str:
    return build_judge_prompt(request_for(path, text))

def review(path: str, text: str, config: dict | None = None, *, ready: Callable[[], bool] = available, complete: Callable[[str, str], str | None] = _run) -> tuple[Note, ...]:
    """No model review without a data boundary, because source text would leave the machine."""
    if config is None or not data_boundary_enabled(config):
        return ()
    if not text.strip() or not ready():
        return ()
    model = str(config.get("adw_model") or REVIEW_MODEL)
    raw = complete(build_prompt(path, text), model)
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
