"""Tests for the PostToolBatch command-line response contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import batch


class BatchBlockTests(unittest.TestCase):
    BLOCK = {
        "decision": "block",
        "reason": "agent-discipline-watcher blocked findings:\nx.py:1 a/b: fix it.",
    }

    def test_a_block_passes_through_unchanged(self):
        out = batch.cli_response(dict(self.BLOCK))
        self.assertEqual(out, self.BLOCK)

    def test_an_allow_passes_through_untouched(self):
        self.assertEqual(batch.cli_response({}), {})

    def test_a_block_without_a_reason_is_not_swallowed(self):
        payload = {"decision": "block"}
        self.assertEqual(batch.cli_response(payload), payload)

    def test_the_entry_script_exits_two_on_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "dirty.py"
            target.write_text(
                "def duplicated(value):\n    return value + 1\n" * 6,
                encoding="utf-8",
            )
            duplicate = root / "duplicate.py"
            duplicate.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            payload = {
                "session_id": "halt-probe",
                "cwd": str(root),
                "hook_event_name": "PostToolBatch",
                "tool_calls": [
                    {
                        "tool_name": "Write",
                        "tool_use_id": "t1",
                        "tool_input": {"file_path": str(target)},
                    },
                    {
                        "tool_name": "Write",
                        "tool_use_id": "t2",
                        "tool_input": {"file_path": str(duplicate)},
                    },
                ],
            }
            script = Path(__file__).resolve().parent / "batch.py"
            result = subprocess.run(
                [sys.executable, str(script)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
                cwd=str(script.parent),
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("duplicate_file_content", result.stderr)
