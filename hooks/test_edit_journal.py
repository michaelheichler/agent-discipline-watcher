"""Tests for the PostToolUse edit journal in record.py."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import record
from lib import reporting, session_state


class EditJournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger_root = self.root / "ledger"
        self.state_root = self.root / "state"
        self.cfg = {
            "ledger_root": str(self.ledger_root),
            "state_root": str(self.state_root),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger_rows(self):
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.ledger_root)

    def _journal_rows(self):
        """Return the edit rows alone, since every invocation also emits one observed heartbeat."""
        return [row for row in self._ledger_rows() if row["event"] == "edit"]

    def _heartbeat_rows(self):
        return [row for row in self._ledger_rows() if row["event"] == "observed"]

    def test_journal_records_one_row_per_edited_path(self):
        target = self.root / "a.py"
        target.write_text("print(1)\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_use_id": "toolu_1",
            "tool_input": {"file_path": str(target)},
        }
        record.run(payload, self.cfg)
        rows = self._journal_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["path"], str(target))
        self.assertEqual(row["tool"], "Write")
        self.assertEqual(row["tool_use_id"], "toolu_1")
        self.assertEqual(row["session_id"], "s1")

    def test_journal_fires_even_when_scan_finds_no_findings(self):
        target = self.root / "a.py"
        target.write_text("print(1)\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        response = record.run(payload, self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(len(self._journal_rows()), 1)

    def test_journal_still_fires_when_scan_blocks(self):
        target = self.root / "a.py"
        # Defer the literal because the discipline scanner would otherwise flag this test file.
        target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        response = record.run(payload, self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertEqual(len(self._journal_rows()), 1)

    def test_an_observed_finding_advises_and_is_recorded_as_would_block(self):
        target = self.root / "a.py"
        target.write_text("# increments the counter\nx = 1\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_use_id": "toolu_2",
            "tool_input": {"file_path": str(target)},
        }
        config = {**self.cfg, "rule_gates": {"what_comment": "observe"}}
        response = record.run(payload, config)
        self.assertNotIn("decision", response)
        self.assertIn("clean_code/what_comment", response["systemMessage"])
        decisions = [row for row in self._ledger_rows() if row["event"] == "PostToolUse"]
        self.assertEqual([(row["rule"], row["outcome"]) for row in decisions],
                         [("what_comment", "would_block")])
        self.assertEqual(decisions[0]["tool_use_id"], "toolu_2")

    def test_a_blocked_finding_is_recorded_as_block(self):
        target = self.root / "a.py"
        target.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        record.run(payload, self.cfg)
        outcomes = {
            row["rule"]: row["outcome"]
            for row in self._ledger_rows() if row["event"] == "PostToolUse"
        }
        self.assertEqual(outcomes["deferred_work_comment"], "block")

    def test_a_clean_edit_records_no_decision_row(self):
        target = self.root / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        record.run(payload, self.cfg)
        self.assertEqual([row for row in self._ledger_rows() if row["event"] == "PostToolUse"], [])

    def test_journal_write_failure_does_not_fail_hook(self):
        read_only = self.root / "ro"
        read_only.mkdir()
        read_only.chmod(0o500)
        target = self.root / "a.py"
        target.write_text("print(1)\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        # The hook returns its normal result because a ledger write must never fail it.
        response = record.run(payload, {"ledger_root": str(read_only)})
        self.assertEqual(response, {})

    def test_patch_command_paths_are_journalled(self):
        patch = (
            "*** Add File: src/new.py\n+print(1)\n"
            "*** Update File: src/old.py\n+print(2)\n"
        )
        payload = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": patch},
            "cwd": str(self.root),
        }
        record.run(payload, self.cfg)
        paths = [row["path"] for row in self._journal_rows()]
        self.assertIn("src/new.py", paths)
        self.assertIn("src/old.py", paths)

    def test_sessionless_invocation_does_not_journal(self):
        # A sessionless invocation skips the journal because it has no session to attribute the edit to.
        target = self.root / "a.py"
        target.write_text("print(1)\n", encoding="utf-8")
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
        response = record.run(payload, self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._ledger_rows(), [])

    def test_posttooluse_emits_one_observed_heartbeat(self):
        """Guard the E10 denominator, because a hook that skips its heartbeat inflates the rate."""
        target = self.root / "a.py"
        target.write_text("print(1)\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        record.run(payload, self.cfg)
        self.assertEqual(len(self._heartbeat_rows()), 1)

    def test_heartbeat_fires_when_no_edit_was_made(self):
        """Guard the denominator on the path where no gate ran, since that turn still happened."""
        payload = {"session_id": "s1", "tool_name": "Read", "tool_input": {}}
        record.run(payload, self.cfg)
        self.assertEqual(self._journal_rows(), [])
        self.assertEqual(len(self._heartbeat_rows()), 1)

    def test_journal_rows_carry_the_session_turn_id(self):
        session_state.write_state("s1", {"turn_id": "turn-7"}, root=self.state_root)
        target = self.root / "a.py"
        target.write_text("print(1)\n", encoding="utf-8")
        payload = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        }
        record.run(payload, self.cfg)
        self.assertEqual(self._journal_rows()[0]["turn_id"], "turn-7")
        self.assertEqual(self._heartbeat_rows()[0]["turn_id"], "turn-7")


if __name__ == "__main__":
    unittest.main()
