"""Separate from the client because a turn boundary is a hook concern and the client must stay usable without one."""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    from .embedding_client import ensure_loaded, release
except ImportError:
    from embedding_client import ensure_loaded, release

DISABLE_ENV = "ADW_EMBEDDING_DISABLED"


def enabled() -> bool:
    return not os.environ.get(DISABLE_ENV, "").strip()


LEASE_DIRECTORY_NAME = "embedding-leases"


def lease_root_for(config: dict) -> str | None:
    """Sits beside the configured state root, because a test that isolates its state root must not reach the real one through this path."""
    state_root = config.get("state_root")
    if not isinstance(state_root, str) or not state_root:
        return None
    return str(Path(state_root).with_name(LEASE_DIRECTORY_NAME))


def owner_pid() -> int:
    """The parent, because the hook itself exits within the second and the session that outlives it is the real holder."""
    return os.getppid()


def open_turn(session_id: str, root: str | None) -> str | None:
    """Swallows every failure because an absent model server must cost the turn nothing at all."""
    if not session_id or not enabled():
        return None
    try:
        return ensure_loaded(session_id, time.time(), root, owner_pid())
    except Exception:
        return None


def close_turn(session_id: str, root: str | None) -> bool:
    """Swallows every failure because a lease left behind expires on its own TTL, while a raised hook costs the user the turn."""
    if not session_id or not enabled():
        return False
    try:
        return release(session_id, time.time(), root)
    except Exception:
        return False
