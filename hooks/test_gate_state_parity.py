"""The edit gate, the post-write gate, and the commit gate must read one gate state, or observe means nothing."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pre_commit
import pre_write
import record
from lib import reporting

HOOKS = Path(__file__).resolve().parent
# Defer the literal because the discipline scanner would otherwise flag this test file.
ENFORCED = "# " + ("TO" + "DO") + " later\nx = 1\n"
OBSERVED = "# increments the counter\nx = 1\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "parity@example.test")
    git(repo, "config", "user.name", "Parity Test")
    return repo


def verdict_class(response: dict) -> str:
    """Reduce either hook's response shape to block, advise, or silent, since the shapes differ but the verdict must not."""
    if response.get("decision") == "block":
        return "block"
    return "advise" if response.get("systemMessage") else "silent"


class VerdictParityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.cfg = {
            "ledger_root": str(self.root / "ledger"),
            "state_root": str(self.root / "state"),
            "baseline": "none",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _both(self, body: str, gates: dict) -> tuple[str, str]:
        target = self.root / "a.py"
        target.write_text(body, encoding="utf-8")
        cfg = {**self.cfg, **gates}
        written = pre_write.run(
            {"session_id": "s1", "tool_input": {"file_path": str(target), "content": body}},
            dict(cfg),
        )
        recorded = record.run(
            {"session_id": "s1", "tool_name": "Write", "tool_input": {"file_path": str(target)}},
            dict(cfg),
        )
        return verdict_class(written), verdict_class(recorded)

    def test_an_observed_rule_advises_in_both_gates(self):
        self.assertEqual(
            self._both(OBSERVED, {"rule_gates": {"what_comment": "observe"}}),
            ("advise", "advise"),
        )

    def test_an_enforced_rule_blocks_in_both_gates(self):
        self.assertEqual(
            self._both(OBSERVED, {"rule_gates": {"what_comment": "enforce"}}),
            ("block", "block"),
        )

    def test_a_rule_switched_off_is_silent_in_both_gates(self):
        self.assertEqual(
            self._both(OBSERVED, {"rule_gates": {"what_comment": "off"}}),
            ("silent", "silent"),
        )

    def test_an_enforced_family_still_blocks_in_both_gates(self):
        self.assertEqual(self._both(ENFORCED, {}), ("block", "block"))

    def test_the_shipped_default_observes_what_comment_in_both_gates(self):
        self.assertEqual(self._both(OBSERVED, {}), ("advise", "advise"))


class DefaultBaselineParityTests(unittest.TestCase):
    """Under the shipped baseline the three gates must agree on a legacy file, which pinning baseline none never proves."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = make_repo(self.root)
        self.target = self.repo / "legacy.py"
        self.target.write_text(ENFORCED, encoding="utf-8")
        git(self.repo, "add", "legacy.py")
        git(self.repo, "commit", "-qm", "seed the inherited debt")
        self.cfg = {
            "ledger_root": str(self.root / "ledger"),
            "state_root": str(self.root / "state"),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _three(self, body: str) -> tuple[str, str, str]:
        written = pre_write.run(
            {"session_id": "s1", "cwd": str(self.repo),
             "tool_input": {"file_path": str(self.target), "content": body}},
            dict(self.cfg),
        )
        self.target.write_text(body, encoding="utf-8")
        recorded = record.run(
            {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Write",
             "tool_input": {"file_path": str(self.target)}},
            dict(self.cfg),
        )
        git(self.repo, "add", "legacy.py")
        committed = pre_commit.run(
            {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": "git commit -m msg"}},
            None, ledger_root=self.root / "ledger", state_root=self.root / "state",
        )
        return verdict_class(written), verdict_class(recorded), verdict_class(committed)

    def test_inherited_debt_blocks_in_no_gate(self):
        self.assertEqual(self._three(ENFORCED + "y = 2\n"), ("advise", "advise", "silent"))

    def test_the_edit_gate_names_the_debt_it_did_not_write(self):
        response = pre_write.run(
            {"cwd": str(self.repo),
             "tool_input": {"file_path": str(self.target), "content": ENFORCED + "y = 2\n"}},
            dict(self.cfg),
        )
        self.assertIn("already carried 2 findings", response["systemMessage"])
        self.assertIn("clean_code/deferred_work_comment", response["systemMessage"])

    def test_debt_the_write_adds_still_blocks_in_every_gate(self):
        self.assertEqual(
            self._three(ENFORCED + "# " + ("TO" + "DO") + " second\n"),
            ("block", "block", "block"),
        )

    def test_an_edit_fragment_answers_for_its_own_text(self):
        """Edit carries new_string alone, so comparing that fragment to the committed whole file would be meaningless."""
        response = pre_write.run(
            {"cwd": str(self.repo),
             "tool_input": {"file_path": str(self.target), "new_string": "# " + ("TO" + "DO") + " third\n"}},
            dict(self.cfg),
        )
        self.assertEqual(verdict_class(response), "block")

    def test_an_edit_fragment_free_of_findings_passes(self):
        response = pre_write.run(
            {"cwd": str(self.repo), "tool_input": {"file_path": str(self.target), "new_string": "y = 2\n"}},
            dict(self.cfg),
        )
        self.assertEqual(verdict_class(response), "silent")


class RecordExitCodeTests(unittest.TestCase):
    """Exit status is the only thing the runtime reads, so the block and advise paths are proved through the process."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, body: str) -> subprocess.CompletedProcess:
        target = self.root / "a.py"
        target.write_text(body, encoding="utf-8")
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
        return subprocess.run(
            [sys.executable, str(HOOKS / "record.py")], input=payload, text=True,
            capture_output=True, check=False, cwd=str(HOOKS),
        )

    def test_an_enforced_finding_exits_two_on_stderr(self):
        result = self._run(ENFORCED)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("clean_code/deferred_work_comment", result.stderr)

    def test_an_observed_finding_exits_zero_with_a_posttooluse_advisory(self):
        result = self._run(OBSERVED)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertIn("clean_code/what_comment", response["systemMessage"])
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("clean_code/what_comment", response["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("decision", response)

    def test_a_clean_file_exits_zero_with_no_advisory(self):
        result = self._run("x = 1\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})


class CommitGateStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = make_repo(self.root)
        self.ledger = self.root / "ledger"

    def tearDown(self):
        self._tmp.cleanup()

    def _gate(self, body: str, config: dict | None = None) -> dict:
        (self.repo / "a.py").write_text(body, encoding="utf-8")
        git(self.repo, "add", "a.py")
        payload = {
            "session_id": "commit-session", "tool_use_id": "toolu_c",
            "cwd": str(self.repo), "tool_input": {"command": "git commit -m msg"},
        }
        return pre_commit.run(payload, config, ledger_root=self.ledger, state_root=self.root / "s")

    def _rows(self) -> list[dict]:
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.ledger)

    def test_an_enforced_finding_blocks_the_commit(self):
        self.assertEqual(verdict_class(self._gate(ENFORCED)), "block")

    def test_a_blocked_commit_still_writes_its_precommit_row(self):
        self._gate(ENFORCED)
        rows = [row for row in self._rows() if row.get("event") == "PreCommit"]
        blocked = [row for row in rows if row["outcome"] == "block"]
        self.assertEqual([row["rule"] for row in blocked], ["deferred_work_comment"])
        self.assertEqual(blocked[0]["hook"], "pre_commit")
        self.assertEqual(blocked[0]["path"], "a.py")

    def test_an_observed_finding_advises_instead_of_blocking(self):
        response = self._gate(OBSERVED)
        self.assertEqual(verdict_class(response), "advise")
        self.assertIn("clean_code/what_comment", response["systemMessage"])

    def test_an_observed_finding_is_recorded_as_would_block(self):
        self._gate(OBSERVED)
        rows = [row for row in self._rows() if row.get("event") == "PreCommit"]
        self.assertEqual([row["outcome"] for row in rows], ["would_block"])

    def test_a_rule_switched_off_neither_blocks_nor_advises(self):
        response = self._gate(OBSERVED, {"rule_gates": {"what_comment": "off"}})
        self.assertEqual(verdict_class(response), "silent")


class CommitMessageScanTests(unittest.TestCase):
    """SKILL.md claims scope over commit text, so the message must be scanned like any other prose."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = make_repo(self.root)
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        git(self.repo, "add", "a.py")

    def tearDown(self):
        self._tmp.cleanup()

    def _gate(self, command: str) -> dict:
        payload = {"cwd": str(self.repo), "tool_input": {"command": command}}
        return pre_commit.run(payload, None, ledger_root=self.root / "l", state_root=self.root / "s")

    def test_a_short_flag_message_is_scanned(self):
        response = self._gate('git commit -m "the tests now pass -- finally"')
        self.assertEqual(response.get("decision"), "block")
        self.assertIn("commit_message.md", response["reason"])
        self.assertIn("punctuation/", response["reason"])

    def test_an_attached_short_flag_value_is_scanned(self):
        self.assertEqual(self._gate('git commit -m"we ship it; it works"').get("decision"), "block")

    def test_a_long_flag_message_is_scanned(self):
        self.assertEqual(
            self._gate('git commit --message "we ship it; it works"').get("decision"), "block"
        )

    def test_an_inline_long_flag_message_is_scanned(self):
        self.assertEqual(
            self._gate('git commit --message="we ship it; it works"').get("decision"), "block"
        )

    def test_a_later_repeated_message_is_scanned_too(self):
        response = self._gate('git commit -m "clean subject" -m "we ship it; it works"')
        self.assertEqual(response.get("decision"), "block")
        self.assertIn("commit_message.md:3", response["reason"])

    def test_a_clean_message_passes(self):
        self.assertEqual(self._gate('git commit -m "add the parity tests"'), {})

    def test_a_file_backed_message_is_left_alone(self):
        self.assertEqual(self._gate("git commit -F notes.txt"), {})

    def test_a_message_outside_a_commit_is_not_scanned(self):
        self.assertEqual(self._gate('git tag -m "we ship it; it works" v1'), {})


class CommitMessageParsingTests(unittest.TestCase):
    def test_repeated_messages_are_joined_as_paragraphs(self):
        self.assertEqual(
            pre_commit._commit_messages('git commit -m first -m second'), ["first", "second"]
        )

    def test_every_inline_spelling_is_read(self):
        command = 'git commit -mone --message=two --message three -m four'
        self.assertEqual(
            pre_commit._commit_messages(command), ["one", "two", "three", "four"]
        )

    def test_a_dangling_flag_yields_nothing(self):
        self.assertEqual(pre_commit._commit_messages("git commit -m"), [])

    def test_a_non_commit_git_command_yields_nothing(self):
        self.assertEqual(pre_commit._commit_messages('git commit-tree -m x'), [])


if __name__ == "__main__":
    unittest.main()
