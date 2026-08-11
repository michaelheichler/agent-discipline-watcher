"""Ledger, wrapper, edit journal, and observe-report tests."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import reporting
import session_state

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LedgerRootTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_root_under_home(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            self.assertEqual(
                reporting._default_ledger_root(),
                Path.home() / ".agent-discipline" / "ledger",
            )

    def test_default_root_prefers_plugin_data_env(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(self.root)}):
            self.assertEqual(reporting._default_ledger_root(), self.root / "ledger")

    def test_ledger_dir_uses_override(self):
        self.assertEqual(reporting._ledger_dir(self.root), self.root)

    def test_ledger_dir_falls_back_to_default(self):
        self.assertEqual(
            reporting._ledger_dir(None), reporting._default_ledger_root()
        )


class AppendRowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger_file(self):
        return self.root / reporting.LEDGER_FILENAME

    def test_append_writes_one_jsonl_line(self):
        reporting.append_row({"a": 1}, self.root)
        lines = self._ledger_file().read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)

    def test_appends_are_compact_single_lines(self):
        # Each row is one physical line because json.dumps escapes embedded newlines.
        reporting.append_row({"a": 1}, self.root)
        reporting.append_row({"b": "two\nlines"}, self.root)
        lines = self._ledger_file().read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)

    def test_creates_missing_directory(self):
        nested = self.root / "deep" / "ledger"
        reporting.append_row({"x": 1}, nested)
        self.assertTrue((nested / reporting.LEDGER_FILENAME).exists())


class UnwritableLedgerTests(unittest.TestCase):
    """The named risk: a ledger write must never fail the hook."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_row_to_unwritable_dir_is_swallowed(self):
        read_only = self.root / "ro"
        read_only.mkdir()
        read_only.chmod(0o500)
        captured = []
        with mock.patch.object(reporting.sys, "stderr") as fake_stderr:
            fake_stderr.write.side_effect = lambda message: captured.append(message)
            reporting.append_row({"a": 1}, read_only)
        self.assertTrue(any("ledger append failed" in message for message in captured))

    def test_unwritable_ledger_does_not_raise_in_gate(self):
        read_only = self.root / "ro"
        read_only.mkdir()
        read_only.chmod(0o500)

        called = {"gate": False}

        def gate(turn_id: str) -> dict:
            called["gate"] = True
            return {"decision": "block", "reason": "x"}

        result = reporting.run_with_ledger(
            hook="pre_write",
            payload={"session_id": "s1"}, gate=gate, ledger_root=read_only,
            state_root=self.root,
        )
        self.assertEqual(result, {"decision": "block", "reason": "x"})
        self.assertTrue(called["gate"])

    def test_gate_result_returned_and_heartbeat_emitted_when_gate_raises(self):
        def gate(turn_id: str) -> dict:
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            reporting.run_with_ledger(
                hook="pre_write",
                payload={"session_id": "s1"}, gate=gate,
                ledger_root=self.root, state_root=self.root,
            )
        # The heartbeat still lands because the wrapper emits it from finally.
        lines = (
            (self.root / reporting.LEDGER_FILENAME)
            .read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(len(lines), 1)


class RecordDecisionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_decision_row_has_named_shape(self):
        reporting.record_decision(
            session_id="s1", hook="pre_write", event="PreToolUse",
            family="punctuation", rule="banned_dash", path="a.py",
            tool_use_id="toolu_1", outcome="block", duration_ms=12,
            turn_id="t1", root=self.root,
        )
        rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, self.root)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            set(row.keys()),
            {
                "ts", "session_id", "hook", "event", "family", "rule", "path",
                "tool_use_id", "turn_id", "outcome", "duration_ms",
            },
        )
        self.assertEqual(row["outcome"], "block")
        self.assertEqual(row["event"], "PreToolUse")

    def test_each_documented_outcome_is_accepted(self):
        for outcome in reporting.OUTCOMES:
            with self.subTest(outcome=outcome):
                reporting.record_decision(
                    session_id="s1", hook="h", event="e", family="f", rule="r",
                    path="p", tool_use_id="t", outcome=outcome,
                    duration_ms=0, root=self.root,
                )
        rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, self.root)
        self.assertEqual([row["outcome"] for row in rows], list(reporting.OUTCOMES))

    def test_unknown_outcome_raises_before_any_write(self):
        with self.assertRaises(ValueError):
            reporting.record_decision(
                session_id="s1", hook="h", event="e", family="f", rule="r",
                path="p", tool_use_id="t", outcome="warn", duration_ms=0,
                root=self.root,
            )
        self.assertFalse((self.root / reporting.LEDGER_FILENAME).exists())


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_heartbeat_row_uses_observed_event_and_blank_outcome(self):
        reporting.record_heartbeat(
            session_id="s1", hook="pre_write",
            turn_id="t9", duration_ms=3, root=self.root,
        )
        rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, self.root)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["event"], "observed")
        self.assertEqual(row["outcome"], "")
        self.assertEqual(row["turn_id"], "t9")
        self.assertEqual(row["duration_ms"], 3)

    def test_run_with_ledger_fires_heartbeat_without_a_gate_decision(self):
        def gate(turn_id: str) -> dict:
            return {}

        reporting.run_with_ledger(
            hook="pre_write",
            payload={"session_id": "s1"}, gate=gate,
            ledger_root=self.root, state_root=self.root,
        )
        rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "observed")


class TurnIdStampingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_turn(self, session_id: str, turn_id: str) -> None:
        session_state.write_state(session_id, {"turn_id": turn_id}, root=self.root)

    def test_wrapper_reads_turn_id_from_session_state(self):
        self._write_turn("s1", "turn-42")
        seen = {}

        def gate(turn_id: str) -> dict:
            seen["turn_id"] = turn_id
            return {}

        reporting.run_with_ledger(
            hook="pre_write",
            payload={"session_id": "s1"}, gate=gate,
            ledger_root=self.root, state_root=self.root,
        )
        self.assertEqual(seen["turn_id"], "turn-42")
        rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, self.root)
        self.assertEqual(rows[0]["turn_id"], "turn-42")

    def test_sessionless_invocation_skips_ledger(self):
        def gate(turn_id: str) -> dict:
            return {}

        reporting.run_with_ledger(
            hook="pre_write",
            payload={}, gate=gate, ledger_root=self.root, state_root=self.root,
        )
        self.assertFalse((self.root / reporting.LEDGER_FILENAME).exists())


class ObserveReportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_filters_family_would_block_rows(self):
        rows = [
            {"family": "english", "outcome": "would_block", "turn_id": "t1"},
            {"family": "english", "outcome": "block", "turn_id": "t2"},
            {"family": "punctuation", "outcome": "would_block", "turn_id": "t3"},
        ]
        for row in rows:
            reporting.append_row(row, self.root)
        result = reporting.observe_report("english", self.root)
        self.assertEqual([row["turn_id"] for row in result], ["t1"])


class FalseSignalRateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_none_below_twenty_distinct_turn_ids(self):
        for index in range(5):
            reporting.append_row(
                {"turn_id": f"t{index}", "family": "english", "outcome": "would_block"},
                self.root,
            )
        self.assertIsNone(reporting.false_signal_rate("english", self.root))

    def test_rate_uses_distinct_turn_ids_not_row_count(self):
        for index in range(20):
            reporting.append_row(
                {"turn_id": f"t{index}", "family": "english", "outcome": "observed"},
                self.root,
            )
        # One hundred rows on a single turn must count as one exposure because a turn is one exposure.
        for _ in range(100):
            reporting.append_row(
                {"turn_id": "only-turn", "family": "english", "outcome": "would_block"},
                self.root,
            )
        reporting.adjudicate("english", "ref", False, self.root)
        reporting.adjudicate("english", "ref2", False, self.root)
        rate = reporting.false_signal_rate("english", self.root)
        # Two false signals over 21 distinct turns, scaled to per-20 because the rate is per 20.
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 2 * 20 / 21)

    def test_true_labels_do_not_count_as_false_signals(self):
        for index in range(20):
            reporting.append_row(
                {"turn_id": f"t{index}", "family": "english", "outcome": "observed"},
                self.root,
            )
        reporting.adjudicate("english", "ref", True, self.root)
        rate = reporting.false_signal_rate("english", self.root)
        self.assertEqual(rate, 0.0)

    def test_other_family_adjudications_excluded(self):
        for index in range(20):
            reporting.append_row(
                {"turn_id": f"t{index}", "family": "english", "outcome": "observed"},
                self.root,
            )
        reporting.adjudicate("punctuation", "ref", False, self.root)
        rate = reporting.false_signal_rate("english", self.root)
        self.assertEqual(rate, 0.0)


class AdjudicateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_persists_label_row(self):
        row = reporting.adjudicate("english", "2026-01-01T00:00:00Z", False, self.root)
        self.assertEqual(row["family"], "english")
        self.assertFalse(row["label"])
        lines = (self.root / reporting.ADJUDICATION_FILENAME).read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 1)

    def test_write_failure_is_swallowed(self):
        read_only = self.root / "ro"
        read_only.mkdir()
        read_only.chmod(0o500)
        captured = []
        with mock.patch.object(reporting.sys, "stderr") as fake_stderr:
            fake_stderr.write.side_effect = lambda message: captured.append(message)
            reporting.adjudicate("english", "ref", False, read_only)
        self.assertTrue(any("adjudication write failed" in message for message in captured))


class CompactBlockRegressionTests(unittest.TestCase):
    def test_compact_block_unchanged_writes_private_full_report(self):
        finding = {
            "path": "a.txt", "family": "english", "rule": "utilize",
            "line": 1, "force": True, "action": "Use 'use'.",
            "snippet": "We util" + "ize this source line",
        }
        reason, report = reporting.compact_block([finding], {"max_rows": 4})
        self.assertIn("Full report:", reason)
        self.assertEqual(oct(os.stat(report).st_mode & 0o777), "0o600")

    @staticmethod
    def _finding(rule: str = "utilize") -> dict:
        return {
            "path": "a.txt", "family": "english", "rule": rule,
            "line": 1, "force": True, "action": "Use 'use'.",
            "snippet": "a source line",
        }

    def test_the_default_lead_line_is_byte_for_byte_unchanged(self):
        reason, _ = reporting.compact_block([self._finding()], {"max_rows": 4})
        self.assertTrue(reason.startswith("agent-discipline-watcher blocked findings:\n"), reason)

    def test_a_caller_supplied_lead_replaces_only_the_first_line(self):
        rows = [self._finding()]
        default, _ = reporting.compact_block(rows, {"max_rows": 4})
        custom, _ = reporting.compact_block(rows, {"max_rows": 4}, lead="lead line:")
        self.assertTrue(custom.startswith("lead line:\n"))
        self.assertEqual(
            custom.split("\n")[1:-1], default.split("\n")[1:-1],
        )

    def test_max_rows_still_caps_the_listing(self):
        reason, _ = reporting.compact_block([self._finding()] * 5, {"max_rows": 2}, lead="x:")
        self.assertIn("... 3 more", reason)


class VerdictMessageTests(unittest.TestCase):
    """One reading of gate state for every hook, so observe cannot mean two different things."""

    @staticmethod
    def _row(rule: str) -> dict:
        return {"path": "a.py", "family": "clean_code", "rule": rule, "line": 1,
                "action": "fix", "snippet": "x"}

    def test_a_blocking_decision_wins_over_an_observed_one(self):
        kind, message = reporting.verdict_message(
            [(self._row("a"), "would_block"), (self._row("b"), "block")], {}
        )
        self.assertEqual(kind, "block")
        self.assertIn("blocked findings:", message)
        self.assertNotIn("a.py:1 clean_code/a:", message)

    def test_an_observed_decision_uses_the_observe_lead(self):
        kind, message = reporting.verdict_message([(self._row("a"), "would_block")], {})
        self.assertEqual(kind, "observe")
        self.assertTrue(message.startswith(reporting.OBSERVE_LEAD))
        self.assertNotIn("blocked findings", message)

    def test_released_decisions_say_nothing(self):
        self.assertEqual(reporting.verdict_message([(self._row("a"), "release")], {}), ("release", ""))

    def test_no_decisions_release(self):
        self.assertEqual(reporting.verdict_message([], {}), ("release", ""))


class InheritedAdviceTests(unittest.TestCase):
    @staticmethod
    def _row(line: int) -> dict:
        return {"path": "old.py", "family": "clean_code", "rule": "what_comment",
                "line": line, "action": "fix", "snippet": "x"}

    def test_it_counts_the_inherited_findings(self):
        message = reporting.inherited_advice([self._row(1), self._row(2)], {})
        self.assertIn("already carried 2 findings you did not write", message)
        self.assertIn("old.py:1 clean_code/what_comment", message)

    def test_an_empty_list_says_nothing(self):
        self.assertEqual(reporting.inherited_advice([], {}), "")

    def test_max_rows_keeps_a_legacy_file_from_flooding_the_response(self):
        message = reporting.inherited_advice([self._row(1)] * 12, {"max_rows": 3})
        self.assertIn("... 9 more", message)
        self.assertEqual(message.count("old.py:1"), 3)


if __name__ == "__main__":
    unittest.main()


class PreGateEvidenceTests(unittest.TestCase):
    """The edit and command gates must leave rows, because a block nobody can count cannot be reviewed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.cfg = {"ledger_root": str(root / "l"), "state_root": str(root / "s")}
        session_state.write_state("probe", {"turn_id": "turn-9"}, root / "s")

    def tearDown(self):
        self._tmp.cleanup()

    def _rows(self):
        path = Path(self.cfg["ledger_root"]) / reporting.LEDGER_FILENAME
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _decisions(self, hook):
        return [row for row in self._rows() if row.get("hook") == hook and row.get("rule")]

    def test_pre_write_records_a_protected_path_block(self):
        import pre_write
        payload = {"session_id": "probe", "tool_use_id": "w1",
                   "tool_input": {"file_path": str(Path.home() / ".claude" / "settings.json"), "content": "{}"}}
        pre_write.run(payload, dict(self.cfg))
        rows = self._decisions("pre_write")
        self.assertEqual([row["rule"] for row in rows], ["live_client_surface"])
        self.assertEqual(rows[0]["outcome"], "block")
        self.assertEqual(rows[0]["turn_id"], "turn-9")

    def test_pre_bash_records_a_commit_gate_bypass(self):
        import pre_bash
        command = "git commit " + "--no-" + "verify -m x"
        pre_bash.run({"session_id": "probe", "tool_use_id": "b1",
                      "tool_input": {"command": command}}, dict(self.cfg))
        rows = self._decisions("pre_bash")
        self.assertEqual([row["rule"] for row in rows], ["commit_gate_bypass"])
        self.assertEqual(rows[0]["outcome"], "block")

    def test_an_observed_finding_is_recorded_as_would_block(self):
        import pre_write
        payload = {"session_id": "probe", "tool_use_id": "w2",
                   "tool_input": {"file_path": "a.py", "content": "# increments the counter\nx = 1\n"}}
        config = {**self.cfg, "rule_gates": {"what_comment": "observe"}}
        pre_write.run(payload, config)
        rows = self._decisions("pre_write")
        self.assertEqual([(row["rule"], row["outcome"]) for row in rows], [("what_comment", "would_block")])

    def test_both_gates_emit_a_heartbeat(self):
        import pre_bash
        pre_bash.run({"session_id": "probe", "tool_input": {"command": "ls"}}, dict(self.cfg))
        self.assertTrue([row for row in self._rows() if row.get("hook") == "pre_bash" and row.get("event") == "observed"])
