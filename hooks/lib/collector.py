"""Reads configuration from roots the caller supplies, because naming a directory here would name a host."""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

try:
    from .configure_policy import EDITABLE_KEY_SET
except ImportError:
    from configure_policy import EDITABLE_KEY_SET

CONFIG_LEAF = "config.json"
MODELS_LEAF = "models.json"
MAX_LEAF_BYTES = 256 * 1024
KNOWN_KEYS = EDITABLE_KEY_SET | {"checks"}


class CollectorError(ValueError):
    """Name the file because a silently skipped root would run a policy nobody chose."""


class Loaded(NamedTuple):
    """Report the sources beside the values because a merge nobody can trace is a merge nobody trusts."""

    values: dict[str, object]
    models: dict[str, object]
    sources: tuple[Path, ...]


def _read_leaf(path: Path) -> dict[str, object] | None:
    try:
        if not path.is_file():
            return None
        raw = path.read_bytes()
    except OSError as exc:
        raise CollectorError(f"{path.name} could not be read at {path}") from exc
    if len(raw) > MAX_LEAF_BYTES:
        raise CollectorError(f"{path.name} exceeds the size limit at {path}")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CollectorError(f"{path.name} is not valid JSON at {path}") from exc
    if not isinstance(parsed, dict):
        raise CollectorError(f"{path.name} must hold a JSON object at {path}")
    return parsed


def _checked_keys(payload: dict[str, object], path: Path) -> dict[str, object]:
    unknown = sorted(set(payload) - KNOWN_KEYS)
    if unknown:
        raise CollectorError(f"{path.name} carries unknown keys {unknown} at {path}")
    return payload


def _usable(root: Path) -> bool:
    try:
        return root.is_dir()
    except OSError:
        return False


def _merge_leaf(into: dict[str, object], path: Path, *, check: bool) -> Path | None:
    payload = _read_leaf(path)
    if payload is None:
        return None
    if check:
        _checked_keys(payload, path)
    for key, value in payload.items():
        into.setdefault(key, value)
    return path


def _root_sources(root: Path, values: dict[str, object], models: dict[str, object]) -> tuple[Path, ...]:
    found = (
        _merge_leaf(values, root / CONFIG_LEAF, check=True),
        _merge_leaf(models, root / MODELS_LEAF, check=False),
    )
    return tuple(path for path in found if path is not None)


def load(roots: tuple[Path, ...]) -> Loaded:
    """Let an earlier root win because the caller orders them from most specific to least."""
    values: dict[str, object] = {}
    models: dict[str, object] = {}
    sources: list[Path] = []
    for root in roots:
        if _usable(root):
            sources.extend(_root_sources(root, values, models))
    return Loaded(values, models, tuple(sources))
