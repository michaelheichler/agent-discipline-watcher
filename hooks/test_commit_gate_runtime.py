"""Runtime proof that the commit gate reaches pre_commit.py, reports a staged finding, and leaves ledger evidence."""
from __future__ import annotations

import json
import os
import shlex
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
DASH = chr(0x2014)


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


def advisory_text(response: dict) -> str:
    specific = response.get("hookSpecificOutput") or {}
    return "\n".join(
        value
        for value in (response.get("systemMessage"), specific.get("additionalContext"))
        if isinstance(value, str)
    )


def assert_style_advisory(testcase: unittest.TestCase, response: dict) -> None:
    testcase.assertIsNone(response.get("decision"), response)
    message = advisory_text(response)
    testcase.assertTrue(message.strip(), response)
    testcase.assertIn("notes.md", message)
    testcase.assertIn("punctuation/banned_dash", message)


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
        assert_style_advisory(self, result)

    def test_clean_staged_tree_is_allowed(self):
        stage(self.repo, "notes.md", CLEAN)
        self.assertEqual(self.gate('git commit -m "docs(x): add notes"'), {})

    def test_block_writes_a_pre_commit_ledger_row(self):
        stage(self.repo, "notes.md", DIRTY)
        self.gate('git commit -m "docs(x): add notes"')
        decisions = [row for row in ledger_rows(self.ledger) if row.get("event") == "PreCommit"]
        self.assertEqual(len(decisions), 1, ledger_rows(self.ledger))
        self.assertEqual(decisions[0]["outcome"], "must_fix")
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
        assert_style_advisory(self, result)
        self.assertEqual(ledger_rows(self.ledger), [])

    def test_commit_message_rewrite_returns_updated_command(self):
        command = 'git commit -m "add' + DASH + 'notes; it\'s 1990\'s"'
        result = self.gate(command)
        specific = result["hookSpecificOutput"]
        updated = specific["updatedInput"]

        self.assertNotEqual(updated["command"], command)
        self.assertEqual(
            pre_commit._commit_messages(updated["command"]),
            ["add-notes. it's 1990s"],
        )
        self.assertIn("[rewritten] commit_message.md:1 punctuation/banned_dash", advisory_text(result))
        self.assertNotIn("[flagged] commit_message.md:1", advisory_text(result))

    def test_rewrite_preserves_surrounding_shell_syntax(self):
        cases = {
            'git commit -m "msg; here" > /dev/null 2>&1':
                "git commit -m 'msg. here' > /dev/null 2>&1",
            "git add *.py && git commit -m 'msg; here'":
                "git add *.py && git commit -m 'msg. here'",
            'cd $HOME/repo && git commit -m "msg; here"':
                "cd $HOME/repo && git commit -m 'msg. here'",
            'for f in a b; do echo $f; done && git commit -m "msg; here"':
                "for f in a b; do echo $f; done && git commit -m 'msg. here'",
            'git commit -am "msg; here"':
                "git commit -am 'msg. here'",
            'FOO=bar git commit -m "msg; here"':
                "FOO=bar git commit -m 'msg. here'",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                updated = self.gate(command)["hookSpecificOutput"]["updatedInput"]
                self.assertEqual(updated["command"], expected)

    def test_rewrite_preserves_multiple_message_spans(self):
        command = 'git commit -m "first' + DASH + 'part" -m "second' + DASH + 'part"'
        result = self.gate(command)
        self.assertEqual(
            result["hookSpecificOutput"]["updatedInput"]["command"],
            "git commit -m first-part -m second-part",
        )

    def test_rewrite_disclosure_is_user_visible(self):
        result = self.gate('git commit -m "msg; here"')
        self.assertIn("systemMessage", result)
        self.assertIn("rewrote the commit message before the commit ran", result["systemMessage"])

    def test_clean_message_has_no_updated_input(self):
        result = self.gate('git commit -m "fix notes"')
        self.assertNotIn("updatedInput", result.get("hookSpecificOutput", {}))

    def test_bundled_and_assignment_messages_are_scanned(self):
        for command in [
            'git commit -am "circle back with the team"',
            'FOO=bar git commit -m "circle back with the team"',
        ]:
            with self.subTest(command=command):
                result = self.gate(command)
                self.assertIn("english/corporate_idiom", advisory_text(result))
                self.assertNotIn("updatedInput", result.get("hookSpecificOutput", {}))

    def test_unfixable_commit_message_keeps_command_unchanged(self):
        command = 'git commit -m "circle back with the team"'
        result = self.gate(command)
        specific = result["hookSpecificOutput"]

        self.assertNotIn("updatedInput", specific)
        self.assertIn("commit_message.md:1 english/corporate_idiom", advisory_text(result))

    def test_rewritten_special_characters_round_trip_through_shell(self):
        command = 'git commit -m "fix' + DASH + 'its apostrophe: it\'s 1990\'s; keep \\"quotes\\""'
        new_command, _changes = pre_commit._rewrite_commit_messages(
            command, pre_commit.effective_config(None)
        )

        self.assertEqual(
            shlex.split(new_command),
            ["git", "commit", "-m", 'fix-its apostrophe: it\'s 1990s. keep "quotes"'],
        )

    def test_list_command_input_returns_normalized_string_shape(self):
        payload = {
            "tool_input": {"command": ["git", "commit", "-m", "bad" + DASH + "dash"]},
            "cwd": str(self.repo),
        }
        result = pre_commit.run(payload, None, ledger_root=self.ledger, state_root=self.state)

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertIsInstance(updated["command"], list)
        self.assertEqual(updated["command"], ["git", "commit", "-m", "bad-dash"])

    def test_list_inline_message_stays_one_element(self):
        command = ["git", "commit", "--message=bad" + DASH + "notes and more"]
        updated, _changes = pre_commit._rewrite_commit_messages(
            command, pre_commit.effective_config(None)
        )
        self.assertEqual(updated, ["git", "commit", "--message=bad-notes and more"])


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
                assert_style_advisory(self, self.gate(command))

    def test_repo_scoped_flag_reaches_the_gate(self):
        assert_style_advisory(self, self.gate(f"git -C {self.repo} commit -m msg"))

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
                assert_style_advisory(self, result)

    def test_config_flag_consumes_its_value_without_moving_cwd(self):
        assert_style_advisory(self, self.gate("git -c core.hooksPath=/dev/null commit -m msg"))

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
        response = json.loads(result.stdout)
        assert_style_advisory(self, response)


if __name__ == "__main__":
    unittest.main()
