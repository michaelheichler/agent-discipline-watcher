"""Runtime proof that the commit gate reaches pre_commit.py, blocks a staged finding, and leaves ledger evidence."""
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
# Built from the code point because writing the character would trip the punctuation family on this file.
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

    def gate(self, command: str) -> dict:
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
        self.assertEqual(result.get("decision"), "block")
        self.assertIn("notes.md", result["reason"])
        self.assertIn("punctuation", result["reason"])

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
        self.assertEqual(decisions[0]["family"], "punctuation")

    def test_gate_emits_a_heartbeat_row_for_the_session(self):
        stage(self.repo, "notes.md", CLEAN)
        self.gate('git commit -m "docs(x): add notes"')
        beats = [row for row in ledger_rows(self.ledger) if row.get("hook") == "pre_commit"]
        self.assertTrue(beats, "the wrapper must leave a heartbeat even when nothing blocks")

    def test_clean_commit_writes_no_block_row(self):
        stage(self.repo, "notes.md", CLEAN)
        self.gate('git commit -m "docs(x): add notes"')
        self.assertEqual([row for row in ledger_rows(self.ledger) if row.get("outcome") == "block"], [])

    def test_sessionless_invocation_writes_nothing(self):
        stage(self.repo, "notes.md", DIRTY)
        payload = {"tool_input": {"command": "git commit -m msg"}, "cwd": str(self.repo)}
        result = pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)
        self.assertEqual(result.get("decision"), "block")
        self.assertEqual(ledger_rows(self.ledger), [])


class CommitCommandFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stage(self.repo, "notes.md", DIRTY)

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, command: str) -> dict:
        payload = {"tool_input": {"command": command}, "cwd": str(self.repo)}
        return pre_commit.run(payload, None, ledger_root=self.root / "l", state_root=self.root / "s")

    def test_commit_forms_reach_the_gate(self):
        forms = [
            "git commit",
            'git commit -m "docs(x): y"',
            "git commit --amend",
            "git commit -a -m msg",
            "git commit --no-verify -m msg",
            "git -c user.name=Someone commit -m msg",
            "cd . && git commit -m msg",
            "env FOO=bar git commit -m msg",
            "command git commit -m msg",
        ]
        for command in forms:
            with self.subTest(command=command):
                self.assertEqual(self.gate(command).get("decision"), "block", command)

    def test_repo_scoped_flag_reaches_the_gate(self):
        self.assertEqual(self.gate(f"git -C {self.repo} commit -m msg").get("decision"), "block")

    def test_repo_redirecting_flags_resolve_to_the_named_work_tree(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        other = make_repo(elsewhere)
        stage(other, "notes.md", DIRTY)
        for command in [
            f"git --work-tree {other} --git-dir {other}/.git commit -m msg",
            f"git --work-tree={other} --git-dir={other}/.git commit -m msg",
            f"git --git-dir {other}/.git commit -m msg",
            f"git --git-dir={other}/.git commit -m msg",
        ]:
            with self.subTest(command=command):
                payload = {"tool_input": {"command": command}, "cwd": str(outside)}
                result = pre_commit.run(
                    payload, None, ledger_root=self.root / "l2", state_root=self.root / "s2"
                )
                self.assertEqual(result.get("decision"), "block", command)
                self.assertIn("notes.md", result["reason"])

    def test_config_flag_consumes_its_value_without_moving_cwd(self):
        self.assertEqual(self.gate("git -c core.hooksPath=/dev/null commit -m msg").get("decision"), "block")

    def test_non_commit_commands_are_ignored(self):
        for command in ["git log -n 5", "git status", "git commit-tree HEAD", "ls -la", "git push"]:
            with self.subTest(command=command):
                self.assertEqual(self.gate(command), {})


class CommitGateDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stage(self.repo, "notes.md", DIRTY)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_sh_pretooluse_route_blocks_a_commit_end_to_end(self):
        # No PreCommit route exists anymore because pre_tool.py fans Bash out to both scanners.
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
        decision = json.loads(result.stdout)
        self.assertEqual(decision.get("decision"), "block")
        self.assertIn("notes.md", decision["reason"])


if __name__ == "__main__":
    unittest.main()
