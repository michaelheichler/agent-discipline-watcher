from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import session_state

KEY = "unresolved_blockers"
REPORT_LINE_RE = re.compile(r"\nFull report: .*?(?=\n|$)")


@dataclass(frozen=True, slots=True)
class BlockerScope:
    session_id: str
    agent_id: str
    root: str | Path | None


def _scope_from_legacy(
    session_id: str,
    values: tuple[object, ...],
    tail_count: int,
) -> tuple[BlockerScope, tuple[object, ...]]:
    if len(values) not in {tail_count + 1, tail_count + 2}:
        raise TypeError("blocker state call has an invalid argument count")
    agent_id = values[0]
    if not isinstance(agent_id, str):
        raise TypeError("blocker state agent_id must be a string")
    has_root = len(values) == tail_count + 2
    root = values[-1] if has_root else None
    if root is not None and not isinstance(root, (str, Path)):
        raise TypeError("blocker state root must be a path or None")
    tail = values[1:-1] if has_root else values[1:]
    return BlockerScope(session_id, agent_id, root), tail


def scope(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get("agent_id")
    return value if isinstance(value, str) else ""


def _bucket(state: dict, agent_id: str) -> dict:
    root = state.get(KEY)
    if not isinstance(root, dict):
        return {"pending": {}, "paths": [], "revision": 0}
    value = root.get(agent_id)
    return value if isinstance(value, dict) else {"pending": {}, "paths": [], "revision": 0}


def _normalized_bucket(bucket: dict) -> tuple[dict[str, str], list[str], int]:
    """Coerce the stored shape here, once, because every mutator and reader needs the same defense against a hand-edited state file."""
    raw_pending = bucket.get("pending")
    raw_paths = bucket.get("paths")
    raw_revision = bucket.get("revision")
    pending = {
        key: value for key, value in raw_pending.items()
        if isinstance(key, str) and isinstance(value, str)
    } if isinstance(raw_pending, dict) else {}
    paths = [value for value in raw_paths if isinstance(value, str)] if isinstance(raw_paths, list) else []
    revision = raw_revision if isinstance(raw_revision, int) and not isinstance(raw_revision, bool) else 0
    return pending, paths, revision


def _update(scope: BlockerScope, mutate: Callable[[dict], dict]) -> None:
    if not scope.session_id:
        raise ValueError("blocker_state requires a non-empty session_id")

    def change(state: dict) -> dict:
        scopes = state.get(KEY)
        scopes = dict(scopes) if isinstance(scopes, dict) else {}
        bucket = _bucket(state, scope.agent_id)
        _pending, _paths, revision = _normalized_bucket(bucket)
        scopes[scope.agent_id] = {**mutate(bucket), "revision": revision + 1}
        return {**state, KEY: scopes}

    session_state.update_state_strict(scope.session_id, change, scope.root)


def set_pending(scope: BlockerScope | str, *values: object) -> None:
    if isinstance(scope, str):
        scope, values = _scope_from_legacy(scope, values, 2)
    if len(values) != 2 or not all(isinstance(value, str) for value in values):
        raise TypeError("set_pending requires string path and reason values")
    path, reason = values

    def mutate(bucket: dict) -> dict:
        pending, _paths, _revision = _normalized_bucket(bucket)
        pending[path or "<turn>"] = REPORT_LINE_RE.sub("", reason)
        return {**bucket, "pending": pending}

    _update(scope, mutate)


def clear_pending(scope: BlockerScope | str, *values: object) -> None:
    if isinstance(scope, str):
        scope, values = _scope_from_legacy(scope, values, 1)
    if len(values) != 1 or not isinstance(values[0], str):
        raise TypeError("clear_pending requires a string path")
    path = values[0]

    def mutate(bucket: dict) -> dict:
        pending, _paths, _revision = _normalized_bucket(bucket)
        pending.pop(path or "<turn>", None)
        return {**bucket, "pending": pending}

    _update(scope, mutate)


def touch_paths(scope: BlockerScope | str, *values: object) -> None:
    if isinstance(scope, str):
        scope, values = _scope_from_legacy(scope, values, 1)
    if (
        len(values) != 1
        or not isinstance(values[0], list)
        or not all(isinstance(path, str) for path in values[0])
    ):
        raise TypeError("touch_paths requires a list of string paths")
    paths = values[0]

    def mutate(bucket: dict) -> dict:
        _pending, existing, _revision = _normalized_bucket(bucket)
        existing.extend(path for path in paths if path and path not in existing)
        return {**bucket, "paths": existing}

    _update(scope, mutate)


def details(session_id: str, agent_id: str, root=None) -> tuple[dict[str, str], list[str], int]:
    bucket = _bucket(session_state.read_state_strict(session_id, root), agent_id)
    return _normalized_bucket(bucket)


def reconcile(scope: BlockerScope | str, *values: object) -> None:
    if isinstance(scope, str):
        scope, values = _scope_from_legacy(scope, values, 3)
    if (
        len(values) != 3
        or not isinstance(values[0], int)
        or isinstance(values[0], bool)
        or not isinstance(values[1], list)
        or not all(isinstance(key, str) for key in values[1])
        or not isinstance(values[2], list)
        or not all(isinstance(path, str) for path in values[2])
    ):
        raise TypeError("reconcile requires a revision and string key and path lists")
    revision, pending_keys, paths = values

    def mutate(bucket: dict) -> dict:
        if bucket.get("revision") != revision:
            return bucket
        pending, existing, _revision = _normalized_bucket(bucket)
        for key in pending_keys:
            pending.pop(key, None)
        removed = set(paths)
        return {**bucket, "pending": pending, "paths": [path for path in existing if path not in removed]}

    _update(scope, mutate)


def snapshot(session_id: str, agent_id: str, root=None) -> tuple[list[str], list[str]]:
    pending, paths, _revision = details(session_id, agent_id, root)
    return list(pending.values()), paths


def scope_ids(session_id: str, root=None) -> list[str]:
    state = session_state.read_state_strict(session_id, root)
    scopes = state.get(KEY)
    return [key for key in scopes if isinstance(key, str)] if isinstance(scopes, dict) else []
