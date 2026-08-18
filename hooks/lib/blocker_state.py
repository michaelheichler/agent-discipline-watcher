from __future__ import annotations

import re

from . import session_state

KEY = "unresolved_blockers"
REPORT_LINE_RE = re.compile(r"\nFull report: .*?(?=\n|$)")


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


def _update(session_id: str, agent_id: str, mutate, root) -> None:
    if not session_id:
        raise ValueError("blocker_state requires a non-empty session_id")
    def change(state: dict) -> dict:
        scopes = state.get(KEY)
        scopes = dict(scopes) if isinstance(scopes, dict) else {}
        bucket = _bucket(state, agent_id)
        _pending, _paths, revision = _normalized_bucket(bucket)
        scopes[agent_id] = {**mutate(bucket), "revision": revision + 1}
        return {**state, KEY: scopes}
    session_state.update_state_strict(session_id, change, root)


def set_pending(session_id: str, agent_id: str, path: str, reason: str, root=None) -> None:
    def mutate(bucket: dict) -> dict:
        pending, _paths, _revision = _normalized_bucket(bucket)
        pending[path or "<turn>"] = REPORT_LINE_RE.sub("", reason)
        return {**bucket, "pending": pending}
    _update(session_id, agent_id, mutate, root)


def clear_pending(session_id: str, agent_id: str, path: str, root=None) -> None:
    def mutate(bucket: dict) -> dict:
        pending, _paths, _revision = _normalized_bucket(bucket)
        pending.pop(path or "<turn>", None)
        return {**bucket, "pending": pending}
    _update(session_id, agent_id, mutate, root)


def touch_paths(session_id: str, agent_id: str, paths: list[str], root=None) -> None:
    def mutate(bucket: dict) -> dict:
        _pending, existing, _revision = _normalized_bucket(bucket)
        existing.extend(path for path in paths if path and path not in existing)
        return {**bucket, "paths": existing}
    _update(session_id, agent_id, mutate, root)


def details(session_id: str, agent_id: str, root=None) -> tuple[dict[str, str], list[str], int]:
    bucket = _bucket(session_state.read_state_strict(session_id, root), agent_id)
    return _normalized_bucket(bucket)


def reconcile(
    session_id: str,
    agent_id: str,
    revision: int,
    pending_keys: list[str],
    paths: list[str],
    root=None,
) -> None:
    def mutate(bucket: dict) -> dict:
        if bucket.get("revision") != revision:
            return bucket
        pending, existing, _revision = _normalized_bucket(bucket)
        for key in pending_keys:
            pending.pop(key, None)
        removed = set(paths)
        return {**bucket, "pending": pending, "paths": [path for path in existing if path not in removed]}
    _update(session_id, agent_id, mutate, root)


def snapshot(session_id: str, agent_id: str, root=None) -> tuple[list[str], list[str]]:
    pending, paths, _revision = details(session_id, agent_id, root)
    return list(pending.values()), paths


def scope_ids(session_id: str, root=None) -> list[str]:
    state = session_state.read_state_strict(session_id, root)
    scopes = state.get(KEY)
    return [key for key in scopes if isinstance(key, str)] if isinstance(scopes, dict) else []
