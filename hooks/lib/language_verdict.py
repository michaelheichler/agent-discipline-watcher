"""Cached under the paragraph hash, because a paragraph may cost at most one Luna call (decision Q16)."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from .judge_contracts import LANGUAGE_CODES, JudgeRequest, ReviewKind
from .luna_storage import LunaProviderFailure
from .prose_language import ParagraphLanguage
from .session_state import plugin_data_home

CACHE_DIRNAME = "language-verdicts"
MAX_PARAGRAPHS = 16
MAX_PARAGRAPH_CHARS = 2000
VERDICT_FIELDS = frozenset({"index", "language"})
Judge = Callable[[JudgeRequest], object]
StateRoot = str | os.PathLike[str] | None
Verdicts = dict[str, str]


def normalized(text: str) -> str:
    return " ".join(text.split())


def verdict_key(text: str) -> str:
    return hashlib.sha256(normalized(text).encode("utf-8")).hexdigest()


def cache_root(state_root: StateRoot = None) -> Path:
    """Beside the judge cache, because retention already sweeps that directory."""
    state = Path(state_root) if state_root is not None else plugin_data_home() / "state"
    return state.parent / "cache" / CACHE_DIRNAME


def cached_language(paragraph_text: str, state_root: StateRoot = None) -> str | None:
    try:
        verdict = (cache_root(state_root) / verdict_key(paragraph_text)).read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    return verdict if verdict in LANGUAGE_CODES else None


def _store(paragraph_text: str, language: str, state_root: StateRoot) -> None:
    """Unlocked, because a torn two-byte read fails the code check and counts as no verdict."""
    root = cache_root(state_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / verdict_key(paragraph_text)).write_text(language, encoding="ascii")


def apply_cached(paragraphs: Iterable[ParagraphLanguage], state_root: StateRoot = None) -> list[ParagraphLanguage]:
    """Weak paragraphs only, because a strong stop-word signal outranks the model."""
    return [_corrected(paragraph, state_root) if paragraph.weak else paragraph for paragraph in paragraphs]


def _corrected(paragraph: ParagraphLanguage, state_root: StateRoot) -> ParagraphLanguage:
    verdict = cached_language(paragraph.text, state_root)
    return paragraph if verdict is None else replace(paragraph, language=verdict, weak=False)


def unresolved(paragraphs: Iterable[ParagraphLanguage], state_root: StateRoot = None) -> list[str]:
    """Deduplicated, because a repeated paragraph must not cost a second call."""
    texts = (normalized(paragraph.text) for paragraph in paragraphs if paragraph.weak)
    return [text for text in dict.fromkeys(texts) if cached_language(text, state_root) is None]


def classify(texts: Iterable[str], judge: Judge, state_root: StateRoot = None) -> Verdicts:
    """Chunked, because one request carries at most sixteen paragraphs."""
    pending = list(dict.fromkeys(normalized(text) for text in texts))
    verdicts: Verdicts = {}
    for start in range(0, len(pending), MAX_PARAGRAPHS):
        verdicts.update(_classify_batch(pending[start:start + MAX_PARAGRAPHS], judge))
    for text, language in verdicts.items():
        _store(text, language, state_root)
    return verdicts


def _classify_batch(batch: list[str], judge: Judge) -> Verdicts:
    """Empty on failure, because the paragraph then keeps the document language."""
    request = JudgeRequest(
        ReviewKind.LANGUAGE, candidates=tuple(text[:MAX_PARAGRAPH_CHARS] for text in batch),
    )
    try:
        result = judge(request)
    except (LunaProviderFailure, OSError):
        return {}
    return parsed(getattr(result, "payload", None), batch)


def parsed(payload: object, batch: list[str]) -> Verdicts:
    """Strict, because a guessed language would switch a paragraph to the wrong rule set."""
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    answers: dict[int, set[str]] = {}
    for row in rows:
        if _well_formed(row, len(batch)):
            answers.setdefault(row["index"], set()).add(row["language"])
    return {batch[index]: min(languages) for index, languages in answers.items() if len(languages) == 1}


def _well_formed(row: object, size: int) -> bool:
    if not isinstance(row, dict) or set(row) != VERDICT_FIELDS:
        return False
    index = row["index"]
    return type(index) is int and 0 <= index < size and row["language"] in LANGUAGE_CODES
