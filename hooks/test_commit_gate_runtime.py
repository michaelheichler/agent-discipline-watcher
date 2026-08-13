"""Runtime proof that commit blockers reach the staged tree and keep commands unchanged."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import pre_commit

ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "hooks" / "run.sh"
DIRTY = "This sentence uses an em dash " + chr(0x2014) + " which the punctuation family blocks.\n"
CLEAN = "This sentence is plain and blocks nothing.\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "gate@example.test")
    git(repo, "config", "user.name", "Gate Test")
    return repo


def stage(repo: Path, name: str, body: str) -> None:
    (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", name)


def ledger_rows(ledger_root: Path) -> list[dict]:
    path = ledger_root / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CommitGateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.ledger = self.root / "ledger"
        self.state = self.root / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, command: str | list[str]) -> dict:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "commit-gate-session",
            "tool_name": "Bash",
            "tool_use_id": "toolu_commit",
            "tool_input": {"command": command},
            "cwd": str(self.repo),
        }
        return pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)

    def test_staged_finding_blocks_the_commit(self):
        stage(self.repo, "notes.md", DIRTY)
        result = self.gate('git commit -m "docs(x): add notes"')

        self.assertEqual(result["decision"], "block")
        self.assertIn("notes.md:1 punctuation/banned_dash", result["reason"])

    def test_clean_staged_tree_is_allowed(self):
        stage(self.repo, "notes.md", CLEAN)
        self.assertEqual(self.gate('git commit -m "docs(x): add notes"'), {})

    def test_block_writes_a_pre_commit_ledger_row(self):
        stage(self.repo, "notes.md", DIRTY)
        self.gate('git commit -m "docs(x): add notes"')
        decisions = [row for row in ledger_rows(self.ledger) if row.get("event") == "PreCommit"]

        self.assertEqual(len(decisions), 1, ledger_rows(self.ledger))
        self.assertEqual(decisions[0]["outcome"], "block")
        self.assertEqual(decisions[0]["hook"], "pre_commit")
        self.assertEqual(decisions[0]["path"], "notes.md")

    def test_sessionless_invocation_still_blocks_without_ledger(self):
        stage(self.repo, "notes.md", DIRTY)
        result = pre_commit.run(
            {"tool_input": {"command": "git commit -m msg"}, "cwd": str(self.repo)},
            None,
            ledger_root=self.ledger,
            state_root=self.state,
        )

        self.assertEqual(result["decision"], "block")
        self.assertEqual(ledger_rows(self.ledger), [])

    def test_commit_message_violation_blocks_without_rewriting_command(self):
        command = 'git commit -m "we ship it; it works"'
        result = self.gate(command)

        self.assertEqual(result["decision"], "block")
        self.assertIn("commit_message.md:1 punctuation/prose_semicolon", result["reason"])
        self.assertNotIn("updatedInput", result["hookSpecificOutput"])
        self.assertEqual(pre_commit._commit_messages(command), ["we ship it; it works"])

    def test_ansi_c_commit_message_with_escaped_apostrophe_is_scanned(self):
        command = r"git commit -m $'we can\'t; it works'"

        result = self.gate(command)

        self.assertEqual(result["decision"], "block")
        self.assertIn("commit_message.md:1 punctuation/prose_semicolon", result["reason"])
        self.assertEqual(pre_commit._commit_messages(command), ["we can't; it works"])

    def test_list_ansi_c_commit_message_with_escaped_apostrophe_is_scanned(self):
        command = ["git", "commit", "-m", "$'your" + "\\'" + "s'"]

        result = self.gate(command)

        self.assertEqual(result["decision"], "block")
        self.assertIn("commit_message.md:1 punctuation/pronoun_apostrophe", result["reason"])
        self.assertEqual(pre_commit._commit_messages(command), ["your's"])

    def test_run_sh_pretooluse_route_blocks_a_commit_end_to_end(self):
        stage(self.repo, "notes.md", DIRTY)
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "docs(x): y"'},
            "cwd": str(self.repo),
        })
        env = dict(os.environ, HOME=str(self.root))
        result = subprocess.run(
            [str(RUN_SH), "PreToolUse"], input=payload, text=True,
            capture_output=True, check=False, env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
