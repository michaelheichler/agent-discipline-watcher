"""Tests for the additive PostToolBatch discipline gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import batch
import record
from lib import reporting, session_state


class BatchGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger_root = self.root / "ledger"
        self.state_root = self.root / "state"
        self.cfg = {
            "ledger_root": str(self.ledger_root),
            "state_root": str(self.state_root),
        }
        session_state.write_state("s1", {"turn_id": "turn-4"}, self.state_root)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def _call(self, path: Path | str, tool_use_id: str | None) -> dict:
        call: dict[str, object] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(path)},
        }
        if tool_use_id is not None:
            call["tool_use_id"] = tool_use_id
        return call

    def _payload(self, calls: object, session_id: str = "s1") -> dict:
        return {
            "session_id": session_id,
            "cwd": str(self.root),
            "hook_event_name": "PostToolBatch",
            "tool_calls": calls,
        }

    def _record_call(self, call: dict, session_id: str = "s1") -> dict:
        return record.run({"session_id": session_id, **call}, self.cfg)

    def _rows(self) -> list[dict]:
        ledger = self.ledger_root / reporting.LEDGER_FILENAME
        if not ledger.exists():
            return []
        rows = []
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _batch_decisions(self) -> list[dict]:
        return [row for row in self._rows() if row.get("event") == "PostToolBatch"]

    def _assert_advisory(self, response: dict, rule: str) -> str:
        self.assertIsNone(response.get("decision"))
        output = response.get("hookSpecificOutput", {})
        self.assertIsInstance(output, dict)
        context = output.get("additionalContext", "")
        self.assertIsInstance(context, str)
        self.assertTrue(context.strip())
        self.assertIn(rule, context)
        return context

    def _duplicate_text(self) -> str:
        return "def duplicated(value):\n    total = value + 1\n    return total\n" * 6

    def test_matching_ids_dedupe_only_canonical_per_call_findings(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "tool-1")
        self._assert_advisory(self._record_call(call), "deferred_work_comment")

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

        self._assert_advisory(response, "deferred_work_comment")

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

        self._assert_advisory(response, "deferred_work_comment")

    def test_unrelated_tool_id_never_suppresses_finding(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        self._record_call(self._call(path, "other-id"))
        path.write_text("# " + ("TO" + "DO") + " later\n", encoding="utf-8")

        response = batch.run(self._payload([self._call(path, "tool-1")]), self.cfg)

        self._assert_advisory(response, "deferred_work_comment")

    def test_matching_id_for_another_path_never_suppresses_finding(self):
        bad = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        clean = self._write("clean.py", "value = 1\n")
        self._record_call(self._call(clean, "tool-1"))

        response = batch.run(self._payload([self._call(bad, "tool-1")]), self.cfg)

        self._assert_advisory(response, "deferred_work_comment")

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

        self._assert_advisory(response, "deferred_work_comment")

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

        self._assert_advisory(response, "duplicate_file_content")

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
        session_state.write_state("single", {"turn_id": "turn-4"}, self.state_root)
        session_state.write_state("repeated", {"turn_id": "turn-4"}, self.state_root)

        single = batch.run(self._payload([call], "single"), self.cfg)
        repeated = batch.run(self._payload([call, duplicate], "repeated"), self.cfg)
        rows = self._rows()
        projections = [
            (
                row["session_id"],
                row["hook"],
                row["event"],
                row["rule"],
                row["path"],
                row["outcome"],
            )
            for row in rows
            if row.get("session_id") in {"single", "repeated"}
        ]

        single_context = self._assert_advisory(single, "deferred_work_comment")
        repeated_context = self._assert_advisory(repeated, "deferred_work_comment")
        self.assertEqual(
            single_context.split("\nFull report:", 1)[0],
            repeated_context.split("\nFull report:", 1)[0],
        )
        self.assertEqual(
            [item[1:] for item in projections if item[0] == "single"],
            [item[1:] for item in projections if item[0] == "repeated"],
        )
        self.assertEqual(
            session_state.read_state("single", self.state_root),
            session_state.read_state("repeated", self.state_root),
        )

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

    def test_arbitrary_size_integers_fully_correlate(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        for digits, value in ((101, 10**100), (5001, 10**5000)):
            with self.subTest(digits=digits):
                call = self._call(path, "same")
                call["tool_input"]["value"] = value
                duplicate = {
                    **call,
                    "tool_input": {
                        "value": value,
                        "file_path": str(path),
                    },
                }

                single = batch.findings_for_batch(
                    self._payload([call]), self.cfg, "turn-4"
                )
                repeated = batch.findings_for_batch(
                    self._payload([call, duplicate]), self.cfg, "turn-4"
                )

                self.assertEqual(repeated, single)
                self.assertIn(
                    "deferred_work_comment", {finding["rule"] for finding in repeated}
                )

    def test_huge_integer_patch_member_is_never_stringified_or_extracted(self):
        call = self._call("ignored.py", "huge-patch")
        del call["tool_input"]["file_path"]
        call["tool_input"]["patch"] = [
            "*** Add File: must-not-scan.py",
            10**5000,
        ]

        with patch.object(batch, "_normalized_path") as normalized_path:
            self.assertEqual(batch.run(self._payload([call]), self.cfg), {})

        normalized_path.assert_not_called()
        self.assertEqual(self._batch_decisions(), [])

    def test_canonical_dict_key_order_collapses(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        first = self._call(path, "same")
        first["tool_input"] = {"file_path": str(path), "value": [True, 1, None]}
        second = self._call(path, "same")
        second["tool_input"] = {"value": [True, 1, None], "file_path": str(path)}

        single = batch.findings_for_batch(self._payload([first]), self.cfg, "turn-4")
        repeated = batch.findings_for_batch(
            self._payload([first, second]), self.cfg, "turn-4"
        )

        self.assertEqual(repeated, single)

    def test_deep_canonical_input_correlates_without_recursion(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        nested: object = "leaf"
        for _ in range(600):
            nested = [nested]
        call = self._call(path, "deep")
        call["tool_input"]["nested"] = nested
        duplicate = dict(call)

        response = batch.run(self._payload([call, duplicate]), self.cfg)

        self._assert_advisory(response, "deferred_work_comment")
        self.assertNotIn(
            batch.DEGRADED_RULE, {row["rule"] for row in self._batch_decisions()}
        )

    def test_canonical_cycles_degrade_but_shared_acyclic_values_correlate(self):
        cycle: list[object] = []
        cycle.append(cycle)
        cyclic_call = self._call("bad.py", "cycle")
        cyclic_call["tool_input"]["nested"] = cycle

        self.assertEqual(batch.run(self._payload([cyclic_call]), self.cfg), {})
        self.assertEqual(self._batch_decisions()[-1]["rule"], batch.DEGRADED_RULE)

        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        shared = [{"value": 1}]
        shared_call = self._call(path, "shared")
        shared_call["tool_input"].update({"left": shared, "right": shared})
        response = batch.run(self._payload([shared_call, dict(shared_call)]), self.cfg)

        self._assert_advisory(response, "deferred_work_comment")
        self.assertNotEqual(self._batch_decisions()[-1]["rule"], batch.DEGRADED_RULE)

    def test_compact_dag_has_linear_work_and_alias_insensitive_equality(self):
        def doubling_dag(depth: int) -> object:
            node: object = {"leaf": 1}
            for _ in range(depth):
                node = [node, node]
            return node

        def duplicated_tree(depth: int) -> object:
            if depth == 0:
                return {"leaf": 1}
            return [duplicated_tree(depth - 1), duplicated_tree(depth - 1)]

        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        first = self._call(path, "dag")
        first["tool_input"]["nested"] = doubling_dag(18)
        second = self._call(path, "dag")
        second["tool_input"]["nested"] = doubling_dag(18)
        original_atom = batch._canonical_atom
        atom_visits = 0

        def count_atom(value: object) -> object:
            nonlocal atom_visits
            atom_visits += 1
            return original_atom(value)

        with patch.object(batch, "_canonical_atom", side_effect=count_atom):
            response = batch.run(self._payload([first, second]), self.cfg)

        self._assert_advisory(response, "deferred_work_comment")
        self.assertNotIn(
            batch.DEGRADED_RULE, {row["rule"] for row in self._batch_decisions()}
        )
        self.assertLessEqual(atom_visits, 20)
        self.assertEqual(
            batch._canonical_value(doubling_dag(6)),
            batch._canonical_value(duplicated_tree(6)),
        )

    def test_shared_dict_is_enumerated_once_and_equals_duplicated_values(self):
        size = 128
        shared = {str(index): index for index in range(size)}
        shared_value = [shared] * size
        duplicated_value = [dict(shared) for _ in range(size)]
        original_keys = batch._exact_dict_keys
        original_atom = batch._canonical_atom
        enumerations = 0
        enumerated_keys = 0
        atom_visits = 0

        def count_keys(mapping: dict[object, object]) -> tuple[object, ...]:
            nonlocal enumerations, enumerated_keys
            keys = original_keys(mapping)
            if mapping is shared:
                enumerations += 1
                enumerated_keys += len(keys)
            return keys

        def count_atom(value: object) -> object:
            nonlocal atom_visits
            atom_visits += 1
            return original_atom(value)

        with (
            patch.object(batch, "_exact_dict_keys", side_effect=count_keys),
            patch.object(batch, "_canonical_atom", side_effect=count_atom),
        ):
            shared_canonical = batch._canonical_value(shared_value)

        self.assertEqual(enumerations, 1)
        self.assertEqual(enumerated_keys, size)
        self.assertEqual(atom_visits, size)
        self.assertEqual(shared_canonical, batch._canonical_value(duplicated_value))

    def test_float_negative_zero_identity_is_preserved(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        positive = self._call(path, "same")
        positive["tool_input"]["value"] = 0.0
        negative = self._call(path, "same")
        negative["tool_input"]["value"] = -0.0

        self.assertEqual(batch.run(self._payload([positive, negative]), self.cfg), {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )

    def test_non_string_path_fields_are_ignored_by_public_run(self):
        for malformed in (1, ["bad.py"], None):
            with self.subTest(file_path=malformed):
                call = self._call(self.root / "bad.py", "tool-1")
                call["tool_input"]["file_path"] = malformed

                self.assertEqual(batch.run(self._payload([call]), self.cfg), {})

    def test_repeated_identical_call_keeps_per_call_findings(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        call = self._call(path, "same")

        single = batch.findings_for_batch(self._payload([call]), self.cfg, "turn-4")
        repeated = batch.findings_for_batch(
            self._payload([call, dict(call)]), self.cfg, "turn-4"
        )

        self.assertEqual(repeated, single)
        self.assertIn("deferred_work_comment", {row["rule"] for row in repeated})

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

    def test_batch_never_firing_leaves_record_behavior_untouched(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")

        response = self._record_call(self._call(path, "tool-1"))

        self._assert_advisory(response, "deferred_work_comment")

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

        self._assert_advisory(response, "deferred_work_comment")

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

        self._assert_advisory(response, "deferred_work_comment")

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

        self._assert_advisory(response, "deferred_work_comment")

    def test_cross_file_finding_is_never_suppressed_by_matching_rows(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())
        calls = [self._call(left, "left"), self._call(right, "right")]
        for call in calls:
            self._record_call(call)

        response = batch.run(self._payload(calls), self.cfg)

        self._assert_advisory(response, "duplicate_file_content")

    def test_symlink_aliases_do_not_trigger_duplicate_file_content(self):
        target = self._write("target.py", self._duplicate_text())
        alias = self.root / "alias.py"
        try:
            alias.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlinks unsupported: {exc}")

        response = batch.run(
            self._payload([self._call(target, None), self._call(alias, None)]),
            self.cfg,
        )

        self.assertEqual(response, {})

    def test_hardlink_aliases_do_not_trigger_duplicate_file_content(self):
        target = self._write("target.py", self._duplicate_text())
        alias = self.root / "alias.py"
        try:
            os.link(target, alias)
        except OSError as exc:
            self.skipTest(f"hardlinks unsupported: {exc}")

        response = batch.run(
            self._payload([self._call(target, None), self._call(alias, None)]),
            self.cfg,
        )

        self.assertEqual(response, {})

    def test_symlink_and_hardlink_aliases_are_one_file(self):
        actual = self._write("actual.py", self._duplicate_text())
        symlink = self.root / "alias.py"
        symlink.symlink_to(actual)
        hardlink = self.root / "hardlink.py"
        os.link(actual, hardlink)
        calls = [
            self._call(actual, None),
            self._call(symlink, None),
            self._call(hardlink, None),
        ]

        self.assertEqual(batch.run(self._payload(calls), self.cfg), {})

    def test_relative_and_absolute_paths_to_one_inode_are_not_duplicates(self):
        actual = self._write("actual.py", self._duplicate_text())

        response = batch.run(
            self._payload(
                [self._call(actual.name, "relative"), self._call(actual, "absolute")]
            ),
            self.cfg,
        )

        self.assertEqual(response, {})
        self.assertNotIn(
            "duplicate_file_content",
            {row["rule"] for row in self._batch_decisions()},
        )

    def test_duplicate_content_requires_200_nonspace_characters(self):
        for size, should_report in ((199, False), (200, True)):
            with self.subTest(size=size):
                session_id = f"boundary-{size}"
                session_state.write_state(
                    session_id, {"turn_id": "turn-4"}, self.state_root
                )
                text = "x" * size
                left = self._write(f"left-{size}.py", text)
                right = self._write(f"right-{size}.py", text)

                response = batch.run(
                    self._payload(
                        [self._call(left, "left"), self._call(right, "right")],
                        session_id,
                    ),
                    self.cfg,
                )

                if should_report:
                    self._assert_advisory(response, "duplicate_file_content")
                else:
                    self.assertEqual(response, {})

    def test_disappearance_between_stat_and_read_is_harmless(self):
        path = self._write("vanishing.py", self._duplicate_text())

        def disappear(candidate: Path, _config: dict) -> None:
            candidate.unlink()

        with patch.object(batch, "read_scannable", side_effect=disappear):
            response = batch.run(self._payload([self._call(path, None)]), self.cfg)

        self.assertEqual(response, {})

    def test_inode_replacement_between_stat_and_read_is_harmless(self):
        path = self._write("first.py", self._duplicate_text())
        stable = self._write("second.py", self._duplicate_text())
        replacement = self._write("replacement.py", self._duplicate_text())
        original_read = batch.read_scannable
        replacements = 0

        def replace(candidate: Path, config: dict) -> str | None:
            nonlocal replacements
            if candidate == path:
                replacement.replace(candidate)
                replacements += 1
            return original_read(candidate, config)

        with patch.object(batch, "read_scannable", side_effect=replace):
            response = batch.run(
                self._payload([self._call(path, None), self._call(stable, None)]),
                self.cfg,
            )

        self.assertEqual(replacements, 1)
        self.assertEqual(response, {})
        self.assertNotIn(
            "duplicate_file_content",
            {row["rule"] for row in self._batch_decisions()},
        )

    def test_in_place_mutation_between_stat_and_read_is_harmless(self):
        original = self._duplicate_text()
        mutated = "x" * len(original)
        changing = self._write("first.py", original)
        stable = self._write("second.py", original)
        original_inode = changing.stat().st_ino
        original_read = batch.read_scannable
        original_fingerprint = batch._stat_fingerprint
        mutations: list[tuple[os.stat_result, os.stat_result]] = []

        def mutate(candidate: Path, config: dict) -> str | None:
            if candidate == changing:
                before = candidate.stat()
                old_text = original_read(candidate, config)
                candidate.write_text(mutated, encoding="utf-8")
                os.utime(candidate, ns=(before.st_atime_ns, before.st_mtime_ns))
                mutations.append((before, candidate.stat()))
                return old_text
            return original_read(candidate, config)

        with patch.object(batch, "read_scannable", side_effect=mutate):
            response = batch.run(
                self._payload([self._call(changing, None), self._call(stable, None)]),
                self.cfg,
            )

        self.assertEqual(len(mutations), 1)
        before, after = mutations[0]
        self.assertEqual(after.st_size, before.st_size)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertNotEqual(after.st_ctime_ns, before.st_ctime_ns)
        self.assertEqual(changing.stat().st_ino, original_inode)
        self.assertEqual(changing.read_text(encoding="utf-8"), mutated)
        self.assertEqual(response, {})
        self.assertNotIn(
            "duplicate_file_content",
            {row["rule"] for row in self._batch_decisions()},
        )

        changing.write_text(original, encoding="utf-8")
        session_state.write_state("mutant", {"turn_id": "turn-4"}, self.state_root)

        def fingerprint_without_ctime(file_stat: os.stat_result) -> tuple[int, ...]:
            return original_fingerprint(file_stat)[:4]

        with (
            patch.object(batch, "read_scannable", side_effect=mutate),
            patch.object(
                batch, "_stat_fingerprint", side_effect=fingerprint_without_ctime
            ),
        ):
            mutant = batch.run(
                self._payload(
                    [self._call(changing, None), self._call(stable, None)],
                    "mutant",
                ),
                self.cfg,
            )

        self.assertEqual(len(mutations), 2)
        self._assert_advisory(mutant, "duplicate_file_content")

    def test_observe_records_cross_file_would_block_without_blocking(self):
        left = self._write("left.py", self._duplicate_text())
        right = self._write("right.py", self._duplicate_text())
        cfg = {**self.cfg, "gates": {"clean_code": "observe"}}

        response = batch.run(
            self._payload([self._call(left, None), self._call(right, None)]), cfg
        )

        self.assertEqual(response, {})
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


if __name__ == "__main__":
    unittest.main()


class BatchReadOnlyToolTests(unittest.TestCase):
    """A file the agent only inspected must never reach the batch scan, whatever its content."""

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


class BatchNeverHaltsTheTurnTests(unittest.TestCase):
    """D13 makes record.py canonical, so the batch layer reports and never ends the turn."""

    BLOCK = {"decision": "block", "reason": "agent-discipline-watcher blocked findings:\nx.py:1 a/b: fix it."}

    def test_a_block_becomes_a_message_carrying_the_same_text(self):
        out = batch.cli_response(dict(self.BLOCK))
        self.assertNotIn("decision", out)
        self.assertEqual(out["systemMessage"], self.BLOCK["reason"])
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], self.BLOCK["reason"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolBatch")

    def test_an_allow_passes_through_untouched(self):
        self.assertEqual(batch.cli_response({}), {})

    def test_a_block_without_a_reason_is_not_swallowed(self):
        payload = {"decision": "block"}
        self.assertEqual(batch.cli_response(payload), payload)

    def test_the_entry_script_exits_zero_on_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "dirty.py"
            target.write_text("# increments the counter\nx = 1\n", encoding="utf-8")
            payload = {
                "session_id": "halt-probe", "cwd": str(root),
                "hook_event_name": "PostToolBatch",
                "tool_calls": [{"tool_name": "Write", "tool_use_id": "t1",
                                "tool_input": {"file_path": str(target)}}],
            }
            script = Path(__file__).resolve().parents[1] / "hooks" / "batch.py"
            result = subprocess.run(
                [sys.executable, str(script)], input=json.dumps(payload),
                capture_output=True, text=True, check=False,
                cwd=str(script.parent),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('"decision"', result.stdout)
