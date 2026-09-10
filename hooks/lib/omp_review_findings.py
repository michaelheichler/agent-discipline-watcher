from __future__ import annotations

import json

from .judge_contracts import ReviewKind, output_schema, validate_payload
from .omp_review_requests import ReviewWork
from .reporting import _safe_text


def _text(value: str) -> str:
    return _safe_text(value).replace("\n", " ").strip()[:800]


def _candidate_findings(work: ReviewWork, payload: dict) -> list[str]:
    items = payload["items"]
    if sorted(row["index"] for row in items) != list(range(len(work.candidates))):
        raise ValueError("review must answer every candidate exactly once")
    violating = "describes_code" if work.request.review_kind is ReviewKind.COMMENT else "violating"
    findings = []
    for row in items:
        if not row["reason"].strip():
            raise ValueError("review candidate has no reason")
        if row["verdict"] != violating:
            continue
        candidate = work.candidates[row["index"]]
        rule = work.request.rule_name or "comment_narration"
        findings.append(f"{_text(work.path)}:{candidate.line}: {rule}: {_text(row['reason'])} Rewrite: {_text(candidate.text)}")
    return findings


def _document_findings(work: ReviewWork, payload: dict) -> list[str]:
    if len(payload["notes"]) > 6:
        raise ValueError("document review exceeds the six-note limit")
    findings = []
    source = work.request.source_context
    for note in payload["notes"]:
        quote = note["quote"]
        if not quote.strip() or quote not in source:
            raise ValueError("document review quote does not occur in the source")
        if not note["problem"].strip() or not note["fix"].strip():
            raise ValueError("document review note has no problem or fix")
        line = work.offset + source[:source.index(quote)].count("\n") + 1
        findings.append(f"{_text(work.path)}:{line}: {_text(note['problem'])} Fix: {_text(note['fix'])}")
    return findings


def validated_findings(work: ReviewWork, output: object) -> dict:
    if not isinstance(output, str) or len(output.encode("utf-8")) > 64 * 1024:
        raise ValueError("model output is absent or exceeds the response limit")
    payload = validate_payload(json.loads(output), output_schema(work.request))
    findings = _document_findings(work, payload) if work.request.review_kind is ReviewKind.DOCUMENT else _candidate_findings(work, payload)
    if not findings:
        return {}
    message = "agent-discipline-watcher OMP review:\n" + "\n".join(findings)
    if work.blocking:
        return {"decision": "block", "reason": message}
    return {"systemMessage": message + "\nThese findings are observed under the current policy."}
