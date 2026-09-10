from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .config import gate_state
from .judge import Candidate, request_for as comment_request
from .judge_contracts import JudgeRequest, ReviewKind, build_prompt, output_schema
from .narration_candidates import candidates
from .pattern_judge import PatternCandidate, request_for as pattern_request
from .pattern_semantic import load_exemplars, load_manifest, rule_prompt
from .regex_judge import judged_rules
from .scanner import PROSE_EXTS, _exempt_families, _is_exempt, scan_all

MAX_BATCH_CANDIDATES = 40
MAX_SOURCE_CHARS = 24_000
MAX_REQUESTS = 16


@dataclass(frozen=True)
class ReviewWork:
    request: JudgeRequest
    path: str
    candidates: tuple[Candidate | PatternCandidate, ...] = ()
    offset: int = 0
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
    return [
        ReviewWork(
            JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context=text[start:start + MAX_SOURCE_CHARS]),
            path, offset=text[:start].count("\n"), blocking=gate_state("english", config) == "enforce",
        )
        for start in range(0, len(text), MAX_SOURCE_CHARS)
        if text[start:start + MAX_SOURCE_CHARS].strip()
    ]


def _pattern_work(path: str, text: str, config: dict) -> list[ReviewWork]:
    found = scan_all(path, text, config)
    rules = judged_rules(config) & {str(item.get("rule")) for item in found}
    if not rules:
        return []
    exemplars, manifest = load_exemplars(), load_manifest()
    work = []
    for rule in sorted(rules):
        if rule not in manifest["rules"]:
            raise ValueError(f"judged rule {rule} has no review rubric")
        selected = tuple(PatternCandidate(path, int(item.get("line") or 1), str(item.get("snippet") or "")) for item in found if item.get("rule") == rule)
        for start in range(0, len(selected), MAX_BATCH_CANDIDATES):
            batch = selected[start:start + MAX_BATCH_CANDIDATES]
            request = pattern_request(rule_prompt(rule, exemplars, manifest), batch)
            work.append(ReviewWork(request, path, batch, blocking=False))
    return work


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
