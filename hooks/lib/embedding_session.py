"""Separate from the client because a turn boundary is a hook concern and the client must stay usable without one."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    from .embedding_client import ensure_loaded, release
    from .embedding_lease import renew
    from .embedding_server import default_root, running_url, start_detached
except ImportError:
    from embedding_client import ensure_loaded, release
    from embedding_lease import renew
    from embedding_server import default_root, running_url, start_detached

ENABLE_ENV = "ADW_EMBEDDING_ENABLED"
DISABLE_ENV = "ADW_EMBEDDING_DISABLED"
CONSUMER_REGISTERED = False
USER_URL_ENVS = ("ADW_EMBEDDING_URL", "ADW_EMBEDDING_URLS")


def enabled() -> bool:
    """Opt in because the qualification gate cut the semantic layer, so provisioning a gigabyte would serve no reader today."""
    if os.environ.get(DISABLE_ENV, "").strip():
        return False
    return bool(os.environ.get(ENABLE_ENV, "").strip())


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


def _needs_supervisor(answered: str | None) -> bool:
    """Skipped for a user URL, because provisioning costs 1.1 GB."""
    if any(os.environ.get(name, "").strip() for name in USER_URL_ENVS):
        return False
    return answered is None or answered == running_url(default_root())


def open_turn(session_id: str, root: str | None) -> str | None:
    """Provisions in the background and answers None for this turn, because a first install downloads most of a gigabyte."""
    if not CONSUMER_REGISTERED or not session_id or not enabled():
        return None
    try:
        answered = ensure_loaded(session_id, time.time(), root, owner_pid())
        if _needs_supervisor(answered):
            start_detached(default_root())
        return answered
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: embedding startup failed: {exc}\n")
        return None


def renew_turn(session_id: str, root: str | None) -> bool:
    """Public for record.py, because a turn past the TTL loses the model."""
    if not session_id:
        return False
    try:
        return renew(session_id, time.time(), root)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: embedding renewal failed: {exc}\n")
        return False


def close_turn(session_id: str, root: str | None) -> bool:
    """Swallowed because a cleanup fault must not block gates."""
    if not session_id:
        return False
    try:
        return release(session_id, root)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: embedding cleanup failed: {exc}\n")
        return False
