"""Real merges here because the gate must tell the agent's own lines from the ones a parent brought in."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import pre_commit
from lib import merge_state
from testing import make_repo, run_git as git

DASH = "This sentence uses an em dash " + chr(0x2014) + " which the punctuation family blocks.\n"
SEMICOLON = "We ship the fix; it works on every host today.\n"
CLEAN = "This sentence is plain and blocks nothing.\n"
MERGE_MESSAGE = 'git commit -m "chore(x): merge upstream work"'


def commit_file(repo: Path, name: str, body: str, message: str = "seed") -> None:
    (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)


def merge_head_file(repo: Path) -> Path:
    return repo / git(repo, "rev-parse", "--git-path", "MERGE_HEAD")


def attempt(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)


class MergeGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.ledger = self.root / "ledger"
        self.state = self.root / "state"
        commit_file(self.repo, "notes.md", CLEAN * 5)
        self.trunk = git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, command: str = MERGE_MESSAGE) -> dict:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "merge-gate-session",
            "tool_name": "Bash",
            "tool_use_id": "toolu_merge",
            "tool_input": {"command": command},
            "cwd": str(self.repo),
        }
        return pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)

    def branch_with(self, name: str, file: str, body: str) -> None:
        git(self.repo, "checkout", "-q", "-b", name, self.trunk)
        commit_file(self.repo, file, body, f"add {file}")
        git(self.repo, "checkout", "-q", self.trunk)

    def diverge_trunk(self) -> None:
        commit_file(self.repo, "other.md", CLEAN, "trunk work")

    def test_a_finding_the_upstream_side_brought_passes_and_stays_reported(self):
        self.branch_with("upstream", "feature.md", CLEAN + DASH)
        self.diverge_trunk()
        git(self.repo, "merge", "-q", "--no-commit", "--no-ff", "upstream")

        result = self.gate()

        self.assertNotEqual(result.get("decision"), "block", result)
        self.assertIn("feature.md:2 Dash character", result["systemMessage"])
        self.assertIn("you did not write", result["systemMessage"])

    def test_the_same_staged_tree_blocks_once_the_merge_state_is_gone(self):
        self.branch_with("upstream", "feature.md", CLEAN + DASH)
        self.diverge_trunk()
        git(self.repo, "merge", "-q", "--no-commit", "--no-ff", "upstream")
        merge_head_file(self.repo).unlink()

        result = self.gate()

        self.assertEqual(result["decision"], "block")
        self.assertIn("feature.md:2 Dash character", result["reason"])

    def test_a_conflict_resolution_that_adds_a_finding_blocks(self):
        self.branch_with("upstream", "notes.md", DASH + CLEAN * 4)
        commit_file(self.repo, "notes.md", CLEAN.replace("plain", "calm") + CLEAN * 4, "trunk edit")
        attempt(self.repo, "merge", "--no-commit", "--no-ff", "upstream")
        commit_file_staged = DASH + SEMICOLON + CLEAN * 4
        (self.repo / "notes.md").write_text(commit_file_staged, encoding="utf-8")
        git(self.repo, "add", "notes.md")

        result = self.gate()

        self.assertEqual(result["decision"], "block")
        self.assertIn("Semicolon in prose", result["reason"])
        self.assertNotIn("Dash character", result["reason"])

    def test_an_octopus_merge_passes_findings_from_every_parent(self):
        self.branch_with("first", "first.md", DASH)
        self.branch_with("second", "second.md", DASH)
        git(self.repo, "merge", "-q", "--no-commit", "first", "second")
        merge_head = merge_head_file(self.repo)
        self.assertEqual(len(merge_head.read_text(encoding="utf-8").split()), 2)

        result = self.gate()

        self.assertNotEqual(result.get("decision"), "block", result)
        self.assertIn("first.md:1 Dash character", result["systemMessage"])
        self.assertIn("second.md:1 Dash character", result["systemMessage"])

    def test_a_cherry_pick_conflict_resolution_passes_the_picked_lines(self):
        self.branch_with("topic", "notes.md", DASH + CLEAN * 4)
        commit_file(self.repo, "notes.md", CLEAN.replace("plain", "calm") + CLEAN * 4, "trunk edit")
        attempt(self.repo, "cherry-pick", "topic")
        (self.repo / "notes.md").write_text(DASH + CLEAN * 4, encoding="utf-8")
        git(self.repo, "add", "notes.md")
        self.assertEqual(merge_state.incoming_commits(self.repo), [git(self.repo, "rev-parse", "topic")])

        result = self.gate('git commit -m "chore(x): pick topic"')

        self.assertNotEqual(result.get("decision"), "block", result)
        self.assertIn("notes.md:1 Dash character", result["systemMessage"])

    def test_a_revert_conflict_resolution_passes_the_restored_lines(self):
        commit_file(self.repo, "notes.md", DASH + CLEAN * 4, "dirty history")
        removal = CLEAN * 4
        commit_file(self.repo, "notes.md", removal, "drop the dirty line")
        commit_file(self.repo, "notes.md", removal.replace("plain", "calm", 1), "later edit")
        attempt(self.repo, "revert", "HEAD~1")
        (self.repo / "notes.md").write_text(DASH + CLEAN * 4, encoding="utf-8")
        git(self.repo, "add", "notes.md")
        self.assertTrue(merge_state.incoming_commits(self.repo))

        result = self.gate('git commit -m "chore(x): revert cleanup"')

        self.assertNotEqual(result.get("decision"), "block", result)
        self.assertIn("notes.md:1 Dash character", result["systemMessage"])

    def test_a_forged_merge_head_on_an_unpublished_commit_launders_nothing(self):
        (self.repo / "notes.md").write_text(CLEAN * 5 + DASH, encoding="utf-8")
        git(self.repo, "add", "notes.md")
        loose = git(
            self.repo, "commit-tree", git(self.repo, "write-tree"), "-p", "HEAD", "-m", "loose",
        )
        merge_head_file(self.repo).write_text(loose + "\n", encoding="utf-8")

        result = self.gate('git commit -m "docs(x): add notes"')

        self.assertEqual(merge_state.incoming_commits(self.repo), [])
        self.assertEqual(result["decision"], "block")

    def test_a_forged_merge_head_with_option_text_is_ignored(self):
        merge_head_file(self.repo).write_text("--output=owned\n", encoding="utf-8")

        self.assertEqual(merge_state.incoming_commits(self.repo), [])
        self.assertFalse((self.repo / "owned").exists())

    def test_a_linked_worktree_reads_its_own_merge_state(self):
        self.branch_with("upstream", "feature.md", CLEAN + DASH)
        linked = self.root / "linked"
        git(self.repo, "worktree", "add", "-q", "-b", "side", str(linked), self.trunk)
        commit_file(linked, "side.md", CLEAN, "side work")
        git(linked, "merge", "-q", "--no-commit", "--no-ff", "upstream")

        self.assertEqual(
            merge_state.incoming_commits(linked), [git(self.repo, "rev-parse", "upstream")],
        )
        self.assertEqual(merge_state.incoming_commits(self.repo), [])


if __name__ == "__main__":
    unittest.main()
