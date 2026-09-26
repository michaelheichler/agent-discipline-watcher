from __future__ import annotations

import hashlib

from . import journal


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
