"""Kept to the general robustness cases and the read-only-tool exemption, because ledger correlation, canonical hashing, and filesystem-race coverage now have their own files (test_batch_correlation.py, test_batch_canonical.py, test_batch_race.py)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import batch
from testing import BatchTestCase


class BatchGateTests(BatchTestCase):
    def test_non_string_path_fields_are_ignored_by_public_run(self):
        for malformed in (1, ["bad.py"], None):
            with self.subTest(file_path=malformed):
                call = self._call(self.root / "bad.py", "tool-1")
                call["tool_input"]["file_path"] = malformed

                self.assertEqual(batch.run(self._payload([call]), self.cfg), {})

    def test_malformed_tool_inputs_and_paths_are_harmless(self):
        calls = [
            {"tool_use_id": "a", "tool_input": "bad-shape"},
            {"tool_use_id": "b", "tool_input": {"file_path": 7}},
        ]

        self.assertEqual(batch.run(self._payload(calls), self.cfg), {})

    def test_non_json_input_forces_cross_file_only_mode(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        calls = [
            {
                "tool_use_id": "same",
                "tool_name": "Write",
                "tool_input": {"file_path": str(bad), "opaque": {1}},
            },
            {
                "tool_use_id": "same",
                "tool_name": "Write",
                "tool_input": {"file_path": str(bad), "opaque": {2}},
            },
        ]

        response = batch.run(self._payload(calls), self.cfg)

        self.assertEqual(response, {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_nul_path_is_harmless(self):
        response = batch.run(
            self._payload([self._call("bad\0path.py", "tool-1")]), self.cfg
        )

        self.assertEqual(response, {})

    def test_absent_batch_is_clean_and_heartbeats(self):
        response = batch.run(
            {"session_id": "s1", "hook_event_name": "PostToolBatch"}, self.cfg
        )

        self.assertEqual(response, {})
        heartbeats = [row for row in self._rows() if row.get("event") == "observed"]
        self.assertEqual(
            [(row["hook"], row["turn_id"]) for row in heartbeats],
            [("batch", "turn-4")],
        )

    def test_empty_batch_is_clean(self):
        self.assertEqual(batch.run(self._payload([]), self.cfg), {})
        self.assertEqual(self._batch_decisions(), [])

    def test_non_dict_raw_batch_call_writes_one_degraded_marker(self):
        self.assertEqual(batch.run(self._payload([7]), self.cfg), {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_raw_non_list_batch_shape_writes_one_degraded_marker(self):
        for malformed in (None, "call", {"tool_use_id": "tool-1"}):
            with self.subTest(tool_calls=malformed):
                before = len(self._batch_decisions())

                self.assertEqual(batch.run(self._payload(malformed), self.cfg), {})
                self.assertEqual(
                    [row["rule"] for row in self._batch_decisions()[before:]],
                    [batch.DEGRADED_RULE],
                )

    def test_observe_records_cross_file_would_block_without_blocking(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())
        cfg = {**self.cfg, "gates": {"clean_code": "observe"}}

        response = batch.run(
            self._payload([self._call(left, None), self._call(right, None)]), cfg
        )

        self.assertNotIn("decision", response)
        self.assertIn("duplicate_file_content", response["systemMessage"])
        self.assertEqual(self._batch_decisions()[0]["outcome"], "would_block")

    def test_off_records_release_without_blocking(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())
        cfg = {**self.cfg, "gates": {"clean_code": "off"}}

        response = batch.run(
            self._payload([self._call(left, None), self._call(right, None)]), cfg
        )

        self.assertEqual(response, {})
        self.assertEqual(self._batch_decisions()[0]["outcome"], "release")


class BatchReadOnlyToolTests(unittest.TestCase):
    """A file the agent only inspected must never reach the batch scan, because a read carries no risk of introducing debt no matter the content."""

    DIRTY = "# increments the counter\nx = 1\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = {
            "ledger_root": str(self.root / "ledger"),
            "state_root": str(self.root / "state"),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def _payload(self, calls: object) -> dict:
        return {
            "session_id": "s1",
            "cwd": str(self.root),
            "hook_event_name": "PostToolBatch",
            "tool_calls": calls,
        }

    def _tool_call(self, tool_name: str, path: Path) -> dict:
        return {
            "tool_name": tool_name,
            "tool_use_id": "tool-1",
            "tool_input": {"file_path": str(path)},
        }

    def test_a_read_of_a_dirty_file_produces_no_batch_finding(self):
        path = self._write("legacy.py", self.DIRTY)
        for tool in ("Read", "Grep", "Glob", "NotebookRead"):
            with self.subTest(tool=tool):
                payload = self._payload([self._tool_call(tool, path)])
                self.assertEqual(batch.findings_for_batch(payload, self.cfg, "turn-4"), [])

        bash_read = {
            "tool_name": "Bash",
            "tool_use_id": "tool-1",
            "tool_input": {"command": f"cat {path}"},
        }
        self.assertEqual(
            batch.findings_for_batch(self._payload([bash_read]), self.cfg, "turn-4"),
            [],
        )

    def test_a_write_of_the_same_file_still_produces_a_finding(self):
        path = self._write("legacy.py", self.DIRTY)
        payload = self._payload([self._tool_call("Write", path)])
        rules = [row["rule"] for row in batch.findings_for_batch(payload, self.cfg, "turn-4")]
        self.assertIn("what_comment", rules)

    def test_write_tool_names_match_the_post_tool_use_matcher(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "hooks" / "hooks.json").read_text())
        groups = config["hooks"]["PostToolUse"]
        matcher = {name.lower() for name in groups[0]["matcher"].split("|")}
        self.assertEqual(matcher, set(batch.WRITE_TOOL_NAMES))


if __name__ == "__main__":
    unittest.main()
