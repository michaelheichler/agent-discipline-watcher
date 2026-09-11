from __future__ import annotations

import hashlib
from typing import Any

from . import journal
from .document_review import request_for as document_request
from .judge_contracts import JudgeRequest, ReviewKind


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
        for offset in range(0, len(source), body_limit):
            context = prefix + source[offset:offset + body_limit]
            if context.strip():
                entries.append((context, row))
    return entries


def _pack_document_entries(entries: list[tuple[str, dict]], content_limit: int) -> list[tuple[str, list[dict]]]:
    packed = []
    current = ""
    sources = []
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
    limit = max(1, maximum)
    use_document_request = len(f"Document: {label}\n\n") < limit
    content_limit = limit - len(f"Document: {label}\n\n") if use_document_request else limit
    contexts = _pack_document_entries(_document_entries(rows, content_limit), content_limit)
    return [
        (
            document_request(label, context) if use_document_request
            else JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context=context),
            sources,
        )
        for context, sources in contexts
    ]


def _source_identities(rows: list[dict]) -> list[dict]:
    identities = {}
    for row in rows:
        _role, path, digest, _line, _text = journal.candidate_key(row)
        if not digest:
            digest = hashlib.sha256(str(row.get("source_context", "")).encode("utf-8")).hexdigest()
        identities[(path, digest)] = {"path": path, "content_hash": digest}
    return list(identities.values())


def feedback_sources(payload: dict, rows: list[dict]) -> list[dict]:
    selected = []
    for note in payload.get("notes", []):
        if not isinstance(note, dict) or not note.get("problem"):
            continue
        quote = note.get("quote")
        matches = [row for row in rows if isinstance(quote, str) and quote and quote in row.get("source_context", "")]
        if not matches:
            return _source_identities(rows)
        selected.extend(matches)
    return _source_identities(selected or rows)
