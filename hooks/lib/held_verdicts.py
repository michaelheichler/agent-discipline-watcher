"""Because an answered pattern is not resent within a turn, its blocking verdict is kept here so a retry cannot release it."""
from __future__ import annotations

import hashlib
import os
import stat
from typing import Any, NamedTuple

CHUNK_BYTES = 64 * 1024
OPEN_FLAGS = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
UPHELD_KEY = "claude_candidate_journal_upheld"
MAX_UPHELD_CHARS = 4000
UPHELD_UNREADABLE = (
    "ADW cannot read the review blocks it holds for this turn, so the turn stays blocked. "
    "Ask the user to start a new session if this message returns."
)
UPHELD_OVER_BOUND = (
    "ADW holds more review blocks for this turn than its journal can carry, so the turn stays blocked "
    "until the flagged files change."
)
UPHELD_UNVERIFIABLE = (
    "ADW cannot read a file that holds a blocked text, so it cannot tell whether the text changed "
    "and the review block stays in force."
)


class Fingerprint(NamedTuple):
    status: str
    digest: str = ""


MISSING = Fingerprint("missing")
OVERSIZED = Fingerprint("oversized")
UNVERIFIABLE = Fingerprint("unverifiable")


def fingerprint(path: str, bound: int) -> Fingerprint:
    """Whole raw bytes, because any content change must release a held block while a touch must not."""
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            return MISSING
        if before.st_size > bound:
            return OVERSIZED
        descriptor = os.open(path, OPEN_FLAGS)
    except (FileNotFoundError, NotADirectoryError):
        return MISSING
    except (OSError, ValueError):
        return UNVERIFIABLE
    try:
        return _hashed(descriptor, before, bound)
    finally:
        os.close(descriptor)


def _hashed(descriptor: int, before: os.stat_result, bound: int) -> Fingerprint:
    """Checked before and after the read, because a file swapped or written mid-read would hash content that never existed."""
    try:
        opened = os.fstat(descriptor)
        digest, size = hashlib.sha256(), 0
        while size <= bound and (chunk := os.read(descriptor, CHUNK_BYTES)):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
    except OSError:
        return UNVERIFIABLE
    if not _identity(before) == _identity(opened) == _identity(after) or size != after.st_size:
        return UNVERIFIABLE
    return Fingerprint("read", digest.hexdigest())


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def with_upheld(state: dict, entries: list[tuple[list[str], str]], live: set[str]) -> dict:
    """Never evicts a live block, because ownership keeps each row in one entry and so bounds the entries by the rows."""
    turn = _turn(state)
    kept = [entry for entry in _entries(state) if entry["turn_id"] == turn]
    fresh = [{"turn_id": turn, "keys": list(keys), "text": text[:MAX_UPHELD_CHARS]} for keys, text in entries if text]
    return {**state, UPHELD_KEY: _owned(kept + fresh, live)}


def upheld_texts(state: dict, live: set[str], row_cap: int) -> list[str]:
    """Only while a covered row is unchanged, because an edit gives the text new keys and earns a fresh review."""
    stored = state.get(UPHELD_KEY)
    entries = _entries(state)
    if stored is not None and (not isinstance(stored, list) or len(entries) < len(stored)):
        return [UPHELD_UNREADABLE]
    texts = [entry["text"] for entry in entries if entry["turn_id"] == _turn(state) and live.intersection(entry["keys"])]
    # Because held rows that fill the cap leave no room for a new candidate.
    return [*texts, UPHELD_OVER_BOUND] if len(live & held_keys(state)) >= row_cap else texts


def held_keys(state: dict) -> set[str]:
    return {key for entry in _entries(state) if entry["turn_id"] == _turn(state) for key in entry["keys"]}


def _owned(entries: list[dict[str, Any]], live: set[str]) -> list[dict[str, Any]]:
    """Newest first, because a later verdict on the same row supersedes the earlier one while every other row keeps its own."""
    claimed: set[str] = set()
    owned: list[dict[str, Any]] = []
    for entry in reversed(entries):
        keys = [key for key in dict.fromkeys(entry["keys"]) if key in live and key not in claimed]
        claimed.update(keys)
        owned.extend([{**entry, "keys": keys}] if keys else [])
    return owned[::-1]


def _turn(state: dict) -> str:
    return str(state.get("turn_id") or "")


def _entries(state: dict) -> list[dict[str, Any]]:
    stored = state.get(UPHELD_KEY)
    entries = stored if isinstance(stored, list) else []
    return [
        entry for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("text"), str) and isinstance(entry.get("turn_id"), str)
        and isinstance(entry.get("keys"), list) and all(isinstance(key, str) for key in entry["keys"])
    ]
