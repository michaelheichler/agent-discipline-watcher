"""Merge state is read here because a commit finishing a merge must not answer for lines the other side wrote."""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

try:
    from . import session_state
except ImportError:
    import session_state

GIT_TIMEOUT_SECONDS = 30
SESSION_STARTED_KEY = "session_started_at"
# Because a revert restores lines from the parent of the reverted commit.
STATE_FILES = (("MERGE_HEAD", ""), ("CHERRY_PICK_HEAD", ""), ("REVERT_HEAD", "^"))
FULL_OBJECT_NAME = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
PUBLISHED_REFS = ("refs/heads", "refs/remotes", "refs/tags")
SHARED_REFS = ("refs/remotes", "refs/tags")


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True, check=False,
            timeout=GIT_TIMEOUT_SECONDS, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def revision_text(repo: Path, revision: str, path: str) -> str | None:
    return _git(repo, "show", f"{revision}:{path}")


def _state_object_names(repo: Path, state_name: str) -> list[str]:
    located = _git(repo, "rev-parse", "--git-path", state_name)
    if not located or not located.strip():
        return []
    try:
        return (repo / located.strip()).read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError):
        return []


def _carried(repo: Path, commit: str, refs: tuple[str, ...]) -> bool:
    carriers = _git(repo, "for-each-ref", "--count=1", "--contains", commit, "--format=%(refname)", *refs)
    return bool(carriers and carriers.strip())


def _older_than(repo: Path, commit: str, started: float) -> bool:
    """Whole seconds on both sides, because a commit stamped in the start second may still come after the start."""
    stamp = _git(repo, "show", "-s", "--format=%ct", commit)
    return bool(stamp and stamp.strip().isdigit() and int(stamp.strip()) < int(started))


def _published(repo: Path, commit: str, started: float | None) -> bool:
    """A local branch tip counts only without a session start, because the agent can create that branch itself."""
    if started is None:
        if _carried(repo, commit, PUBLISHED_REFS):
            return True
        return _git(repo, "merge-base", "--is-ancestor", commit, "HEAD") is not None
    return _carried(repo, commit, SHARED_REFS) or _older_than(repo, commit, started)


def _resolved(repo: Path, name: str, suffix: str, started: float | None) -> str | None:
    if not FULL_OBJECT_NAME.fullmatch(name):
        return None
    commit = _git(repo, "rev-parse", "--verify", "--quiet", f"{name}{suffix}^{{commit}}")
    return commit.strip() if commit and _published(repo, commit.strip(), started) else None


def _state_commits(repo: Path, state_name: str, suffix: str, started: float | None) -> list[str]:
    names = _state_object_names(repo, state_name)
    return [commit for commit in (_resolved(repo, name, suffix, started) for name in names) if commit]


def incoming_commits(repo: Path, session_started: float | None = None) -> list[str]:
    """Return the commits an unfinished merge, cherry-pick or revert brings in, because only those lines are not the agent's."""
    return [
        commit
        for state_name, suffix in STATE_FILES
        for commit in _state_commits(repo, state_name, suffix, session_started)
    ]


def session_started(session_id: str, state_root: str | Path | None) -> float | None:
    """None on any failure, because a session that began before this key existed keeps the old merge rule."""
    try:
        value = session_state.read_state(session_id, state_root).get(SESSION_STARTED_KEY)
    except (OSError, ValueError, TypeError):
        return None
    return float(value) if type(value) in (int, float) else None


def mark_session_start(session_id: str, state_root: str | Path | None) -> None:
    """Seeded only into empty state, because a session with older state must keep the old merge rule."""
    if session_state.read_state(session_id, state_root):
        return
    session_state.update_state(
        session_id, lambda state: state or {SESSION_STARTED_KEY: time.time()}, state_root,
    )
