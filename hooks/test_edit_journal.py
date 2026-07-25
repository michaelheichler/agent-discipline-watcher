"""Tests for the PostToolUse edit journal in record.py."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import record
from lib import reporting


class EditJournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger_root = self.root / "ledger"
        self.cfg = {"ledger_root": str(self.ledger_root)}

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger_rows(self):
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.ledger_root)

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
        rows = self._ledger_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["event"], "edit")
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
        self.assertEqual(len(self._ledger_rows()), 1)

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
        rows = self._ledger_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "edit")

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
        rows = self._ledger_rows()
        paths = [row["path"] for row in rows]
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


if __name__ == "__main__":
    unittest.main()
