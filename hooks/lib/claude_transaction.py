"""Split from the settings writer, because validating a transaction needs no file descriptor."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    from .claude_quarantine import reclaim_quarantines
except ImportError:
    from claude_quarantine import reclaim_quarantines

RENAME_ATTEMPTS = 32
HASH_DIGITS = "0123456789abcdef"
HASH_LENGTH = 64
METADATA_FIELDS = 6
REQUIRED = frozenset({"version", "preset", "base_preset", "base_settings_hash"})
OPTIONAL = frozenset({"base_managed_hash", "base_settings_metadata"})


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == HASH_LENGTH
        and all(character in HASH_DIGITS for character in value)
    )


def _check_shape(payload: object, presets: Sequence[str], version: int) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("preset transaction must be a JSON object")
    keys = set(payload)
    if (
        not keys.issubset(REQUIRED | OPTIONAL)
        or not REQUIRED.issubset(keys)
        or payload.get("version") != version
        or payload.get("preset") not in presets
    ):
        raise ValueError("invalid preset transaction")
    if payload["base_preset"] is not None and payload["base_preset"] not in presets:
        raise ValueError("invalid base preset in transaction")
    return payload


def validate_payload(text: str, presets: Sequence[str], version: int) -> dict[str, Any]:
    """Checked whole, because a transaction trusted halfway rewrites the user's settings."""
    try:
        parsed = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read preset transaction: {exc}") from exc
    payload = _check_shape(parsed, presets, version)
    if payload["base_settings_hash"] is not None and not _is_hash(payload["base_settings_hash"]):
        raise ValueError("invalid base settings hash in transaction")
    managed_hash = payload.get("base_managed_hash")
    if managed_hash is not None and not _is_hash(managed_hash):
        raise ValueError("invalid base managed hash in transaction")
    metadata = payload.get("base_settings_metadata")
    if metadata is not None and (
        not isinstance(metadata, list)
        or len(metadata) != METADATA_FIELDS
        or any(type(value) is not int or value < 0 for value in metadata)
    ):
        raise ValueError("invalid base settings metadata in transaction")
    return payload


def quarantine(
    transaction: Path,
    open_parent: Callable[[Path], int],
    corrupt_suffix: str,
    max_quarantines: int,
    max_bytes: int,
) -> None:
    """Bounds arrive as arguments, because a caller's test patches them on the caller's module."""
    prefix = transaction.name[:64] or "adw.txn"
    try:
        parent_fd = open_parent(transaction)
    except OSError:
        return
    try:
        reclaim_quarantines(parent_fd, prefix, corrupt_suffix, max_quarantines, max_bytes)
        for _attempt in range(RENAME_ATTEMPTS):
            candidate = f"{prefix}{corrupt_suffix}{secrets.token_hex(8)}"
            try:
                os.rename(transaction.name, candidate, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            except FileNotFoundError:
                return
            except FileExistsError:
                continue
            except OSError:
                return
            reclaim_quarantines(parent_fd, prefix, corrupt_suffix, max_quarantines, max_bytes)
            return
    finally:
        os.close(parent_fd)
