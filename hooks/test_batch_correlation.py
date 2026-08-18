"""Split out of test_batch.py because its 964 lines mixed ledger correlation, canonical hashing, and filesystem-race concerns behind one shared class."""
from __future__ import annotations

import unittest
from pathlib import Path

import batch
from lib import reporting, session_state
from testing import BatchTestCase


class BatchCorrelationTests(BatchTestCase):
    def test_matching_ids_dedupe_only_canonical_per_call_findings(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "tool-1")
        self.assert_block(self._record_call(call), "deferred_work_comment")

        response = batch.run(self._payload([call]), self.cfg)

        self.assertEqual(response, {})
        self.assertEqual(self._batch_decisions(), [])

    def test_prior_turn_row_never_suppresses_current_finding(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "tool-1")
        session_state.write_state("s1", {"turn_id": "turn-3"}, self.state_root)
        self._record_call(call)
        session_state.write_state("s1", {"turn_id": "turn-4"}, self.state_root)

        path.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")
        response = batch.run(self._payload([call]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_bash_write_is_correlated_across_turns(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        write_call = self._call(path, "write-1")
        session_state.write_state("s1", {"turn_id": "turn-3"}, self.state_root)
        self._record_call(write_call)
        session_state.write_state("s1", {"turn_id": "turn-4"}, self.state_root)
        path.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")

        bash_call = {
            "tool_name": "Bash",
            "tool_use_id": "bash-1",
            "tool_input": {"command": f'echo "x" > {path}'},
        }
        findings = batch.findings_for_batch(
            self._payload([bash_call]), self.cfg, "turn-4"
        )
        self.assertIn("deferred_work_comment", {finding["rule"] for finding in findings})

        self._record_call(bash_call)
        self.assertEqual(
            batch.findings_for_batch(self._payload([bash_call]), self.cfg, "turn-4"),
            [],
        )

    def test_current_turn_row_suppresses_current_finding(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "tool-1")
        self._record_call(call)

        self.assertEqual(batch.run(self._payload([call]), self.cfg), {})

    def test_unrelated_session_row_never_suppresses_finding(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "tool-1")
        self._record_call(call, session_id="other")
        path.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")

        response = batch.run(self._payload([call]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_unrelated_tool_id_never_suppresses_finding(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        self._record_call(self._call(path, "other-id"))
        path.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")

        response = batch.run(self._payload([self._call(path, "tool-1")]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_matching_id_for_another_path_never_suppresses_finding(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")
        self._record_call(self._call(clean, "tool-1"))

        response = batch.run(self._payload([self._call(bad, "tool-1")]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_same_session_row_from_another_turn_never_suppresses(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        reporting.append_row(
            {
                "session_id": "s1",
                "hook": "record",
                "event": "edit",
                "tool_use_id": "tool-1",
                "path": str(path),
                "turn_id": "turn-3",
            },
            self.ledger_root,
        )

        response = batch.run(self._payload([self._call(path, "tool-1")]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_missing_id_for_one_call_forces_cross_file_only_mode(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")
        calls = [self._call(bad, "tool-1"), self._call(clean, None)]

        response = batch.run(self._payload(calls), self.cfg)

        self.assertEqual(response, {})
        self.assertEqual(
            [(row["rule"], row["outcome"]) for row in self._batch_decisions()],
            [("degraded_cross_file_only", "release")],
        )

    def test_missing_ids_still_emit_cross_file_finding(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())

        response = batch.run(
            self._payload([self._call(left, None), self._call(right, None)]),
            self.cfg,
        )

        self.assert_block(response, "duplicate_file_content")

    def test_duplicate_ids_force_cross_file_only_mode(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")
        calls = [self._call(bad, "same"), self._call(clean, "same")]

        self.assertEqual(batch.run(self._payload(calls), self.cfg), {})
        self.assertEqual(self._batch_decisions()[0]["rule"], "degraded_cross_file_only")

    def test_exact_duplicate_call_matches_single_public_behavior(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(bad, "tool-1")
        call["tool_input"] = {"file_path": str(bad), "content": "bad"}
        duplicate = {
            "irrelevant_metadata": "ignored",
            "tool_input": {"content": "bad", "file_path": str(bad)},
            "tool_name": "Write",
            "tool_use_id": "tool-1",
        }
        for session_id in ("single", "repeated"):
            session_state.write_state(session_id, {"turn_id": "turn-4"}, self.state_root)

        single = self.assert_block(batch.run(self._payload([call], "single"), self.cfg), "deferred_work_comment")
        repeated_calls = [call, duplicate]
        repeated = self.assert_block(
            batch.run(self._payload(repeated_calls, "repeated"), self.cfg), "deferred_work_comment"
        )
        self._assert_single_and_repeated_agree(single, repeated)

    def _assert_single_and_repeated_agree(self, single_context: str, repeated_context: str) -> None:
        self.assertEqual(
            single_context.split("\nFull report:", 1)[0],
            repeated_context.split("\nFull report:", 1)[0],
        )
        rows = self._rows()
        self.assertEqual(self._session_rows(rows, "single"), self._session_rows(rows, "repeated"))
        self.assertEqual(
            session_state.read_state("single", self.state_root),
            session_state.read_state("repeated", self.state_root),
        )

    def _session_rows(self, rows: list[dict], session_id: str) -> list[tuple]:
        return [
            (row["hook"], row["event"], row["rule"], row["path"], row["outcome"])
            for row in rows
            if row.get("session_id") == session_id
        ]

    def test_same_id_same_path_with_distinct_semantics_degrades(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        write_call = self._call(bad, "same")
        edit_call = self._call(bad, "same")
        edit_call["tool_name"] = "Edit"
        edit_call["tool_input"] = {
            "file_path": str(bad),
            "old_string": "later",
            "new_string": "soon",
        }

        response = batch.run(self._payload([write_call, edit_call]), self.cfg)

        self.assertEqual(response, {})
        self.assertEqual(
            [(row["rule"], row["outcome"]) for row in self._batch_decisions()],
            [(batch.DEGRADED_RULE, "release")],
        )

    def test_normalized_path_collision_does_not_hide_id_reuse(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        alias = self.root / "sub" / ".." / bad.name

        response = batch.run(
            self._payload([self._call(bad, "same"), self._call(alias, "same")]),
            self.cfg,
        )

        self.assertEqual(response, {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_duplicate_id_on_different_paths_remains_degraded(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")

        response = batch.run(
            self._payload([self._call(bad, "same"), self._call(clean, "same")]),
            self.cfg,
        )

        self.assertEqual(response, {})
        self.assertEqual(self._batch_decisions()[0]["rule"], batch.DEGRADED_RULE)

    def test_duplicate_call_reordering_does_not_change_findings(self):
        left = self._write("left.py", "# " + ("TO" + "DO") + " later\n")
        right = self._write("right.py", "# " + ("TO" + "DO") + " later\n")
        left_call = self._call(left, "left")
        right_call = self._call(right, "right")
        calls = [left_call, right_call, left_call]

        first = batch.findings_for_batch(self._payload(calls), self.cfg)
        second = batch.findings_for_batch(
            self._payload(list(reversed(calls))), self.cfg
        )

        self.assertEqual(first, second)

    def test_repeated_identical_call_keeps_per_call_findings(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "same")

        single = batch.findings_for_batch(self._payload([call]), self.cfg, "turn-4")
        repeated = batch.findings_for_batch(
            self._payload([call, dict(call)]), self.cfg, "turn-4"
        )

        self.assertEqual(repeated, single)
        self.assertIn("deferred_work_comment", {row["rule"] for row in repeated})

    def test_reordering_calls_does_not_change_findings(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())
        calls = [self._call(left, "left"), self._call(right, "right")]

        first = batch.findings_for_batch(self._payload(calls), self.cfg, "turn-4")
        second = batch.findings_for_batch(
            self._payload(list(reversed(calls))), self.cfg, "turn-4"
        )

        self.assertEqual(first, second)

    def test_malformed_ledger_rows_are_ignored(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        reporting.append_row(
            {"session_id": "s1", "tool_use_id": "tool-1"},
            self.ledger_root,
        )
        ledger = self.ledger_root / reporting.LEDGER_FILENAME
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write("not-json\n")

        response = batch.run(self._payload([self._call(path, "tool-1")]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_no_session_id_uses_cross_file_only_mode_without_ledger(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        payload = self._payload([self._call(bad, "tool-1")])
        del payload["session_id"]

        self.assertEqual(batch.run(payload, self.cfg), {})
        self.assertFalse((self.ledger_root / reporting.LEDGER_FILENAME).exists())

    def test_missing_turn_uses_cross_file_only_mode_with_marker(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        session_state.write_state("s1", {}, self.state_root)

        response = batch.run(self._payload([self._call(bad, "tool-1")]), self.cfg)

        self.assertEqual(response, {})
        self.assertEqual(
            [(row["rule"], row["turn_id"]) for row in self._batch_decisions()],
            [(batch.DEGRADED_RULE, "")],
        )

    def test_exact_current_row_without_turn_never_suppresses(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        reporting.append_row(
            {
                "session_id": "s1",
                "hook": "record",
                "event": "edit",
                "tool_use_id": "tool-1",
                "path": str(path),
            },
            self.ledger_root,
        )

        response = batch.run(self._payload([self._call(path, "tool-1")]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_normalized_ledger_alias_never_suppresses_raw_path(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        (self.root / "sub").mkdir()
        raw_path = str(Path("sub") / ".." / path.name)
        reporting.append_row(
            {
                "session_id": "s1",
                "hook": "record",
                "event": "edit",
                "tool_use_id": "tool-1",
                "path": path.name,
                "turn_id": "turn-4",
            },
            self.ledger_root,
        )

        response = batch.run(self._payload([self._call(raw_path, "tool-1")]), self.cfg)

        self.assert_block(response, "deferred_work_comment")

    def test_cross_file_finding_is_never_suppressed_by_matching_rows(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())
        calls = [self._call(left, "left"), self._call(right, "right")]
        for call in calls:
            self._record_call(call)

        response = batch.run(self._payload(calls), self.cfg)

        self.assert_block(response, "duplicate_file_content")

    def test_batch_never_firing_leaves_record_behavior_untouched(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")

        response = self._record_call(self._call(path, "tool-1"))

        self.assert_block(response, "deferred_work_comment")


if __name__ == "__main__":
    unittest.main()
