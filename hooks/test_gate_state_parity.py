"""All gates must preserve the nonblocking policy for style findings.

Enforcement means deterministic pre-write cleanup where possible, followed by
itemized ``must_fix`` advisories for anything that remains. Only security and
self-protection rules may hard-block a tool call.
"""
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
    """Reduce either hook response shape to a shared verdict label.

The shapes differ, but style findings must remain advisory across gates; only
security/self-protection findings may produce ``block``.
"""
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

    def test_an_observed_rule_is_cleaned_pre_write_and_advises_post_write(self):
        self.assertEqual(
            self._both(OBSERVED, {"rule_gates": {"what_comment": "observe"}}),
            ("silent", "advise"),
        )

    def test_an_enforced_rule_is_cleaned_pre_write_and_advises_post_write(self):
        self.assertEqual(
            self._both(OBSERVED, {"rule_gates": {"what_comment": "enforce"}}),
            ("silent", "advise"),
        )

    def test_a_rule_switched_off_is_silent_in_both_gates(self):
        self.assertEqual(
            self._both(OBSERVED, {"rule_gates": {"what_comment": "off"}}),
            ("silent", "silent"),
        )

    def test_an_enforced_family_is_cleaned_pre_write_and_advises_post_write(self):
        self.assertEqual(self._both(ENFORCED, {}), ("silent", "advise"))

    def test_the_shipped_default_cleans_what_comment_pre_write_and_advises_post_write(self):
        self.assertEqual(self._both(OBSERVED, {}), ("silent", "advise"))


class DefaultBaselineParityTests(unittest.TestCase):
    """The shipped baseline keeps inherited style debt advisory across all gates.

Write-back may leave the commit gate silent once a file on disk is clean, but
must decline to touch a file that mixes inherited and new debt; new debt that
remains on disk must continue to advise at commit time.
"""

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

    def test_inherited_debt_is_advisory_before_commit_and_silent_at_commit(self):
        self.assertEqual(self._three(ENFORCED + "y = 2\n"), ("advise", "advise", "silent"))

    def test_the_edit_gate_names_the_debt_it_did_not_write(self):
        response = pre_write.run(
            {"cwd": str(self.repo),
             "tool_input": {"file_path": str(self.target), "content": ENFORCED + "y = 2\n"}},
            dict(self.cfg),
        )
        self.assertIn("already carried 1 findings", response["systemMessage"])
        self.assertIn("clean_code/deferred_work_comment", response["systemMessage"])

    def test_new_debt_stays_advisory_when_sharing_a_file_with_inherited_debt(self):
        self.assertEqual(
            self._three(ENFORCED + "# " + ("TO" + "DO") + " second\n"),
            ("advise", "advise", "advise"),
        )

    def test_an_edit_fragment_answers_for_its_own_text(self):
        """Edit carries new_string alone, so comparing that fragment to the committed whole file would be meaningless."""
        response = pre_write.run(
            {"cwd": str(self.repo),
             "tool_input": {"file_path": str(self.target), "new_string": "# " + ("TO" + "DO") + " third\n"}},
            dict(self.cfg),
        )
        self.assertEqual(verdict_class(response), "silent")

    def test_an_edit_fragment_free_of_findings_passes(self):
        response = pre_write.run(
            {"cwd": str(self.repo), "tool_input": {"file_path": str(self.target), "new_string": "y = 2\n"}},
            dict(self.cfg),
        )
        self.assertEqual(verdict_class(response), "silent")


class RecordExitCodeTests(unittest.TestCase):
    """Prove process behavior for style findings and the block-only exit path.

A ``must_fix`` advisory exits successfully and reports on stdout; only a
security/self-protection ``block`` should exit 2 and write to stderr.
"""

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

    def test_an_enforced_finding_exits_zero_with_advisory_stdout(self):
        result = self._run(ENFORCED)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean_code/deferred_work_comment", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_default_what_comment_exits_zero_with_advisory_stdout(self):
        result = self._run(OBSERVED)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean_code/what_comment", result.stdout)
        self.assertEqual(result.stderr, "")

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

    def test_an_enforced_finding_advises_on_the_commit(self):
        config = {"rule_gates": {"what_comment": "off"}}
        self.assertEqual(verdict_class(self._gate(ENFORCED, config)), "advise")

    def test_an_advised_commit_still_writes_its_precommit_row(self):
        self._gate(ENFORCED, {"rule_gates": {"what_comment": "off"}})
        rows = [row for row in self._rows() if row.get("event") == "PreCommit"]
        must_fix = [row for row in rows if row["outcome"] == "must_fix"]
        self.assertEqual([row["rule"] for row in must_fix], ["deferred_work_comment"])
        self.assertEqual(must_fix[0]["hook"], "pre_commit")
        self.assertEqual(must_fix[0]["path"], "a.py")

    def test_an_observed_finding_advises_instead_of_blocking(self):
        config = {"rule_gates": {"what_comment": "observe"}}
        response = self._gate(OBSERVED, config)
        self.assertEqual(verdict_class(response), "advise")
        self.assertIn("clean_code/what_comment", response["systemMessage"])

    def test_an_observed_finding_is_recorded_as_would_block(self):
        self._gate(OBSERVED, {"rule_gates": {"what_comment": "observe"}})
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
        self.assertEqual(verdict_class(response), "advise")
        self.assertIn("commit_message.md", response["systemMessage"])
        self.assertIn("punctuation/", response["systemMessage"])

    def test_an_attached_short_flag_value_is_scanned(self):
        response = self._gate('git commit -m"we ship it; it works"')
        self.assertEqual(verdict_class(response), "advise")

    def test_a_long_flag_message_is_scanned(self):
        response = self._gate('git commit --message "we ship it; it works"')
        self.assertEqual(verdict_class(response), "advise")

    def test_an_inline_long_flag_message_is_scanned(self):
        response = self._gate('git commit --message="we ship it; it works"')
        self.assertEqual(verdict_class(response), "advise")

    def test_a_later_repeated_message_is_scanned_too(self):
        response = self._gate('git commit -m "clean subject" -m "we ship it; it works"')
        self.assertEqual(verdict_class(response), "advise")
        self.assertIn("commit_message.md:3", response["systemMessage"])

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
