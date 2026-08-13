"""Tests for the PostToolBatch command-line response contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import batch
from lib import blocker_state


class BatchBlockTests(unittest.TestCase):
    BLOCK = {
        "decision": "block",
        "reason": "agent-discipline-watcher blocked findings:\nx.py:1 a/b: fix it.",
    }

    def test_a_block_becomes_feedback_that_keeps_the_loop_alive(self):
        out = batch.cli_response(dict(self.BLOCK))
        self.assertNotIn("decision", out)
        self.assertIn("blocked findings", out["hookSpecificOutput"]["additionalContext"])

    def test_an_allow_passes_through_untouched(self):
        self.assertEqual(batch.cli_response({}), {})

    def test_a_block_without_a_reason_still_returns_feedback(self):
        payload = {"decision": "block"}
        self.assertIn("additionalContext", batch.cli_response(payload)["hookSpecificOutput"])

    def test_the_entry_script_returns_feedback_on_a_finding(self):
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
            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            self.assertNotIn("decision", response)
            self.assertIn("duplicate_file_content", response["hookSpecificOutput"]["additionalContext"])

    def test_an_undecidable_batch_stays_pending_until_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"state_root": str(Path(tmp) / "state")}
            payload = {"session_id": "s1", "agent_id": "a1"}
            with mock.patch.object(batch, "_run", side_effect=RuntimeError("broken gate")):
                response = batch.run(payload, config)
            self.assertEqual(response["decision"], "block")
            reasons, _paths = blocker_state.snapshot("s1", "a1", config["state_root"])
            self.assertIn("could not evaluate this batch", reasons[0])

    def test_an_undecidable_batch_still_blocks_when_state_write_fails(self):
        payload = {"session_id": "s1"}
        with mock.patch.object(batch, "_run", side_effect=RuntimeError("broken gate")):
            with mock.patch.object(blocker_state, "set_pending", side_effect=OSError("read only")):
                response = batch.run(payload, {})
        self.assertEqual(response["decision"], "block")
        self.assertIn("broken gate", response["reason"])
