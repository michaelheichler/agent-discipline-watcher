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


def _update(session_id: str, agent_id: str, mutate, root) -> None:
    if not session_id:
        return
    def change(state: dict) -> dict:
        scopes = state.get(KEY)
        scopes = dict(scopes) if isinstance(scopes, dict) else {}
        bucket = _bucket(state, agent_id)
        revision = bucket.get("revision")
        revision = revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
        scopes[agent_id] = {**mutate(bucket), "revision": revision + 1}
        return {**state, KEY: scopes}
    session_state.update_state_strict(session_id, change, root)


def set_pending(session_id: str, agent_id: str, path: str, reason: str, root=None) -> None:
    def mutate(bucket: dict) -> dict:
        pending = bucket.get("pending")
        pending = dict(pending) if isinstance(pending, dict) else {}
        pending[path or "<turn>"] = REPORT_LINE_RE.sub("", reason)
        return {**bucket, "pending": pending}
    _update(session_id, agent_id, mutate, root)


def clear_pending(session_id: str, agent_id: str, path: str, root=None) -> None:
    def mutate(bucket: dict) -> dict:
        pending = bucket.get("pending")
        pending = dict(pending) if isinstance(pending, dict) else {}
        pending.pop(path or "<turn>", None)
        return {**bucket, "pending": pending}
    _update(session_id, agent_id, mutate, root)


def touch_paths(session_id: str, agent_id: str, paths: list[str], root=None) -> None:
    def mutate(bucket: dict) -> dict:
        existing = bucket.get("paths")
        values = list(existing) if isinstance(existing, list) else []
        values.extend(path for path in paths if path and path not in values)
        return {**bucket, "paths": values}
    _update(session_id, agent_id, mutate, root)


def details(session_id: str, agent_id: str, root=None) -> tuple[dict[str, str], list[str], int]:
    bucket = _bucket(session_state.read_state_strict(session_id, root), agent_id)
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
        pending = bucket.get("pending")
        pending = dict(pending) if isinstance(pending, dict) else {}
        for key in pending_keys:
            pending.pop(key, None)
        existing = bucket.get("paths")
        existing = list(existing) if isinstance(existing, list) else []
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
