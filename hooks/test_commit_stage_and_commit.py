"""Real repos here, because the commit gate reads the index that staging in the same command would rewrite."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_commit
from lib import reporting
from testing import make_repo, run_git as git

SEED = "This sentence is plain and blocks nothing.\n"
CLEAN = "This sentence is plain and still blocks nothing.\n"
DIRTY = "This sentence uses an em dash " + chr(0x2014) + " which the punctuation family blocks.\n"
MESSAGE = '"docs: update the note"'
COMMIT = f"git commit -m {MESSAGE}"
Texts = tuple[str, str]


def _repo(tmp_path: Path, staged: str, worktree: str) -> Path:
    repo = make_repo(tmp_path)
    note = repo / "note.md"
    note.write_text(SEED, encoding="utf-8")
    git(repo, "add", "note.md")
    git(repo, "commit", "-q", "-m", "seed")
    note.write_text(staged, encoding="utf-8")
    git(repo, "add", "note.md")
    note.write_text(worktree, encoding="utf-8")
    return repo


def _gate(tmp_path: Path, repo: Path, command: str) -> dict:
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "stage-and-commit",
        "tool_name": "Bash",
        "tool_use_id": "toolu_commit",
        "tool_input": {"command": command},
        "cwd": str(repo),
    }
    return pre_commit.run(payload, None, ledger_root=tmp_path / "ledger", state_root=tmp_path / "state")


def _recorded_rules(tmp_path: Path) -> set[str]:
    return {row.get("rule") for row in reporting.read_jsonl(reporting.LEDGER_FILENAME, tmp_path / "ledger")}


@pytest.mark.parametrize("command", [
    f"git add -A && {COMMIT}",
    f"git add -A; {COMMIT}",
    f"git commit -a -m {MESSAGE}",
    f"git commit --all -m {MESSAGE}",
    f"git commit -am {MESSAGE}",
    f"git commit note.md -m {MESSAGE}",
    f"git commit -m {MESSAGE} note.md",
    f"git commit -m {MESSAGE} -- note.md",
    f"git commit -i note.md -m {MESSAGE}",
])
def test_a_commit_that_takes_content_from_outside_the_index_is_denied(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path, SEED, DIRTY)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


def test_staging_and_committing_in_one_command_is_denied_without_judging_the_stale_index(tmp_path: Path) -> None:
    repo = _repo(tmp_path, DIRTY, CLEAN)

    result = _gate(tmp_path, repo, f"git add -A && {COMMIT}")

    assert result.get("decision") == "block"
    assert "banned_dash" not in _recorded_rules(tmp_path)


@pytest.mark.parametrize(("staged_then_worktree", "decision"), [
    ((DIRTY, CLEAN), None),
    ((SEED, DIRTY), "block"),
], ids=["clean-after-add", "violating-after-add"])
def test_a_commit_after_a_separate_staging_call_judges_the_updated_index(tmp_path: Path, staged_then_worktree: Texts, decision: str | None) -> None:
    repo = _repo(tmp_path, *staged_then_worktree)
    git(repo, "add", "-A")

    result = _gate(tmp_path, repo, COMMIT)

    assert result.get("decision") == decision
