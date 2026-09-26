from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import journal
from .config import JUDGED_STATE, gate_state, rule_state
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, ReviewKind, build_prompt, output_schema
from .narration_candidates import candidates
from .pattern_judge import PatternCandidate, request_for as pattern_request
from .pattern_semantic import blocking_rules, load_exemplars, load_manifest, rule_prompt
from .regex_judge import judged_rules
from .scanner import PROSE_EXTS, _exempt_families, _is_exempt, scan_all

MAX_BATCH_CANDIDATES = 40
MAX_SOURCE_CHARS = 24_000
MAX_DOCUMENT_CHARS = 128 * 1024
MAX_REQUESTS = 16


@dataclass(frozen=True)
class ReviewWork:
    request: JudgeRequest
    path: str
    candidates: tuple[Candidate | PatternCandidate, ...] = ()
    blocking: bool = True


def _comment_work(path: str, text: str, config: dict) -> list[ReviewWork]:
    if Path(path).suffix.lower() == ".py":
        try:
            ast.parse(text)
        except SyntaxError as exc:
            raise ValueError(f"could not parse Python source for comment review: {path}:{exc.lineno}") from exc
    found = candidates(path, text)
    work = []
    for start in range(0, len(found), MAX_BATCH_CANDIDATES):
        batch = found[start:start + MAX_BATCH_CANDIDATES]
        if sum(len(item.text) for item in batch) > MAX_SOURCE_CHARS:
            raise ValueError("comment review exceeds the source limit; split the comments")
        work.append(ReviewWork(comment_request(batch), path, batch, blocking=gate_state("clean_code", config) == "enforce"))
    return work


def _document_work(path: str, text: str, config: dict) -> list[ReviewWork]:
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ValueError("document review exceeds the source limit; split the document")
    if not text.strip():
        return []
    return [ReviewWork(
        JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context=text),
        path, blocking=gate_state("english", config) == "enforce",
    )]


def _judged_blocks(rule: str, found: list[dict], config: dict) -> bool:
    """Blocks once confirmed, because the reader removed the false hits."""
    families = {str(item.get("family") or "english") for item in found if item.get("rule") == rule}
    return all(gate_state(family, config) == "enforce" for family in families)


def _batches(found: tuple[PatternCandidate, ...]) -> list[tuple[PatternCandidate, ...]]:
    return [found[start:start + MAX_BATCH_CANDIDATES] for start in range(0, len(found), MAX_BATCH_CANDIDATES)]


def _regex_work(path: str, text: str, config: dict, exemplars: tuple) -> list[ReviewWork]:
    """Only rules without exemplars, because the vote covers the rest."""
    found = scan_all(path, text, config)
    voted = {row.rule for row in exemplars}
    rules = (judged_rules(config) - voted) & {str(item.get("rule")) for item in found}
    manifest = load_manifest()
    work = []
    for rule in sorted(rules):
        if rule not in manifest["rules"]:
            raise ValueError(f"judged rule {rule} has no review rubric")
        selected = tuple(PatternCandidate(path, int(item.get("line") or 1), str(item.get("snippet") or "")) for item in found if item.get("rule") == rule)
        blocking = _judged_blocks(rule, found, config)
        prompt = rule_prompt(rule, exemplars, manifest)
        work.extend(ReviewWork(pattern_request(prompt, batch), path, batch, blocking=blocking) for batch in _batches(selected))
    return work


def _journal_rows(config: dict) -> list[dict]:
    """Empty on a bad session id, because no journal can exist."""
    session_id = config.get("session_id")
    state_root = config.get("state_root")
    if not isinstance(session_id, str) or not session_id:
        return []
    try:
        return journal.read(session_id, state_root=state_root if isinstance(state_root, str) else None)
    except ValueError:
        return []


def _journal_candidates(path: str, text: str, config: dict) -> dict[str, tuple[PatternCandidate, ...]]:
    identity = str(Path(path).expanduser().resolve())
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    grouped: dict[str, list[PatternCandidate]] = {}
    for row in _journal_rows(config):
        if row.get("role") == "pattern" and row.get("path_identity") == identity and row.get("content_hash") == digest:
            grouped.setdefault(str(row.get("rule")), []).append(PatternCandidate(path, int(row["line"]), str(row["text"])))
    return {rule: tuple(found) for rule, found in grouped.items()}


def _voted_state(rule: str, config: dict) -> str:
    return rule_state(rule, config) or gate_state("english", config)


def _voted_work(path: str, text: str, config: dict, exemplars: tuple) -> list[ReviewWork]:
    """Journal rows, because the vote already ran after the write."""
    manifest = load_manifest()
    blocking = blocking_rules(manifest)
    work = []
    for rule, found in sorted(_journal_candidates(path, text, config).items()):
        state = _voted_state(rule, config)
        if rule not in manifest["rules"] or state == "off":
            continue
        prompt = rule_prompt(rule, exemplars, manifest)
        blocks = state in {"enforce", JUDGED_STATE} and rule in blocking
        work.extend(ReviewWork(pattern_request(prompt, batch), path, batch, blocking=blocks) for batch in _batches(found))
    return work


def _pattern_work(path: str, text: str, config: dict) -> list[ReviewWork]:
    exemplars = load_exemplars()
    return _voted_work(path, text, config, exemplars) + _regex_work(path, text, config, exemplars)


def build_work(path: Path, text: str, config: dict) -> tuple[ReviewWork, ...]:
    if _is_exempt(str(path), config):
        return ()
    exempt = _exempt_families(str(path), config)
    work = []
    if "clean_code" not in exempt and gate_state("clean_code", config) != "off":
        work.extend(_comment_work(str(path), text, config))
    if path.suffix.lower() in PROSE_EXTS and "english" not in exempt and gate_state("english", config) != "off":
        work.extend(_document_work(str(path), text, config))
        work.extend(_pattern_work(str(path), text, config))
    if len(work) > MAX_REQUESTS:
        raise ValueError(f"review needs {len(work)} requests, above the limit of {MAX_REQUESTS}; split the file")
    return tuple(work)


def wire_request(index: int, work: ReviewWork) -> dict:
    request = work.request
    return {
        "id": index, "kind": request.review_kind.value,
        "candidate_count": len(request.candidates),
        "prompt": build_prompt(request), "schema": output_schema(request),
    }
