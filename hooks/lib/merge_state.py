"""Merge state is read here because a commit finishing a merge must not answer for lines the other side wrote."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 30
# Because a revert restores lines from the parent of the reverted commit.
STATE_FILES = (("MERGE_HEAD", ""), ("CHERRY_PICK_HEAD", ""), ("REVERT_HEAD", "^"))
FULL_OBJECT_NAME = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
PUBLISHED_REFS = ("refs/heads", "refs/remotes", "refs/tags")


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True,
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


def _published(repo: Path, commit: str) -> bool:
    """Require a branch, tag or history behind the commit, because a stash commit would otherwise launder an agent's own lines."""
    carriers = _git(
        repo, "for-each-ref", "--count=1", "--contains", commit,
        "--format=%(refname)", *PUBLISHED_REFS,
    )
    if carriers and carriers.strip():
        return True
    return _git(repo, "merge-base", "--is-ancestor", commit, "HEAD") is not None


def _resolved(repo: Path, name: str, suffix: str) -> str | None:
    if not FULL_OBJECT_NAME.fullmatch(name):
        return None
    commit = _git(repo, "rev-parse", "--verify", "--quiet", f"{name}{suffix}^{{commit}}")
    return commit.strip() if commit and _published(repo, commit.strip()) else None


def _state_commits(repo: Path, state_name: str, suffix: str) -> list[str]:
    names = _state_object_names(repo, state_name)
    return [commit for commit in (_resolved(repo, name, suffix) for name in names) if commit]


def incoming_commits(repo: Path) -> list[str]:
    """Return the commits an unfinished merge, cherry-pick or revert brings in, because only those lines are not the agent's."""
    return [
        commit
        for state_name, suffix in STATE_FILES
        for commit in _state_commits(repo, state_name, suffix)
    ]
