"""Gate-state schema, outcome resolution, and state-transition tests."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

import config
import reporting
import session_state


def _read_ledger(root: Path) -> list[dict]:
    path = root / reporting.LEDGER_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class GateStateTests(unittest.TestCase):
    def test_each_family_defaults_to_enforce(self):
        for family in config.GATE_FAMILIES:
            self.assertEqual(config.gate_state(family), "enforce", family)

    def test_off_observe_enforce_resolve_from_gates(self):
        for family in config.GATE_FAMILIES:
            for state in config.GATE_STATES:
                cfg = {"gates": {family: state}}
                self.assertEqual(config.gate_state(family, cfg), state, f"{family}/{state}")

    def test_legacy_boolean_false_is_off(self):
        self.assertEqual(config.gate_state("clean_code", {"clean_code": False}), "off")

    def test_legacy_boolean_true_is_enforce(self):
        self.assertEqual(config.gate_state("clean_code", {"clean_code": True}), "enforce")

    def test_kill_switch_forces_off_for_ordinary_findings(self):
        cfg = {"gates": {"clean_code": "enforce"}, "kill_switches": {"clean_code": True}}
        self.assertEqual(config.gate_state("clean_code", cfg), "off")

    def test_invalid_gate_value_falls_back_to_boolean(self):
        cfg = {"gates": {"english": "maybe"}, "english": True}
        self.assertEqual(config.gate_state("english", cfg), "enforce")


class ResolveOutcomeTests(unittest.TestCase):
    def _finding(self, family: str, rule: str = "some_rule") -> dict:
        return {"family": family, "rule": rule}

    def test_every_state_of_every_family(self):
        expected = {"off": "release", "observe": "would_block", "enforce": "block"}
        for family in config.GATE_FAMILIES:
            for state in config.GATE_STATES:
                cfg = {"gates": {family: state}}
                self.assertEqual(
                    config.resolve_outcome(self._finding(family), cfg),
                    expected[state],
                    f"{family}/{state}",
                )

    def test_observe_produces_would_block_not_block(self):
        cfg = {"gates": {"clean_code": "observe"}}
        self.assertEqual(config.resolve_outcome(self._finding("clean_code"), cfg), "would_block")

    def test_off_finding_releases(self):
        cfg = {"gates": {"english": "off"}}
        self.assertEqual(config.resolve_outcome(self._finding("english"), cfg), "release")

    def test_always_blocking_rules_survive_every_gate_state(self):
        for rule in config.ALWAYS_BLOCKING_RULES:
            for state in config.GATE_STATES:
                cfg = {"gates": {"clean_code": state}}
                self.assertEqual(
                    config.resolve_outcome(self._finding("clean_code", rule), cfg),
                    "block",
                    f"{rule}/{state}",
                )

    def test_always_blocking_rules_survive_kill_switch(self):
        cfg = {"kill_switches": {"clean_code": True}}
        for rule in config.ALWAYS_BLOCKING_RULES:
            self.assertEqual(config.resolve_outcome(self._finding("clean_code", rule), cfg), "block")

    def test_always_blocking_rules_survive_family_off(self):
        cfg = {"gates": {"clean_code": "off"}, "kill_switches": {"clean_code": True}}
        for rule in config.ALWAYS_BLOCKING_RULES:
            self.assertEqual(config.resolve_outcome(self._finding("clean_code", rule), cfg), "block")

    def test_full_defeat_all_families_off_all_kill_switches_still_blocks(self):
        defeat = {
            "gates": {f: "off" for f in config.GATE_FAMILIES},
            "kill_switches": {f: True for f in config.GATE_FAMILIES},
            "clean_code": False,
        }
        for rule in config.ALWAYS_BLOCKING_RULES:
            self.assertEqual(
                config.resolve_outcome(self._finding("clean_code", rule), defeat),
                "block",
                f"{rule} must survive full defeat",
            )

    def test_scanner_emits_and_resolve_blocks_always_on_under_full_defeat(self):
        import scanner
        defeat = {
            "gates": {f: "off" for f in config.GATE_FAMILIES},
            "kill_switches": {f: True for f in config.GATE_FAMILIES},
            "clean_code": False,
            "exempt_paths": ["a.py"],
        }
        # Concatenated because the literal marker text in source trips the scanner on this file.
        marker = "craftsman" + "-ignore"
        text = f"# what the code does here\nx = 1  # {marker}: PY002\n"
        findings = scanner.scan_all("a.py", text, defeat)
        always_on = [f for f in findings if f["rule"] in config.ALWAYS_BLOCKING_RULES]
        self.assertEqual(
            {f["rule"] for f in always_on},
            set(config.SCANNER_ALWAYS_BLOCKING_RULES),
        )
        for finding in always_on:
            self.assertEqual(config.resolve_outcome(finding, defeat), "block")

    def test_self_protection_rules_block_under_full_defeat(self):
        defeat = {
            "gates": {f: "off" for f in config.GATE_FAMILIES},
            "kill_switches": dict.fromkeys(config.GATE_FAMILIES, True),
            "self_protection": False,
            "clean_code": False,
            "exempt_paths": ["a.py"],
        }
        defeat["kill_switches"]["self_protection"] = True
        for rule in sorted(config.SELF_PROTECTION_RULES):
            with self.subTest(rule=rule):
                finding = self._finding("self_protection", rule)
                self.assertEqual(config.resolve_outcome(finding, defeat), "block")

    def test_self_protection_rules_are_all_always_blocking(self):
        self.assertTrue(config.SELF_PROTECTION_RULES <= config.ALWAYS_BLOCKING_RULES)
        self.assertFalse(config.SELF_PROTECTION_RULES & config.SCANNER_ALWAYS_BLOCKING_RULES)


class StateTransitionTests(unittest.TestCase):
    def setUp(self):
        self._state_tmp = tempfile.TemporaryDirectory()
        self._ledger_tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self._state_tmp.name)
        self.ledger_root = Path(self._ledger_tmp.name)

    def tearDown(self):
        self._state_tmp.cleanup()
        self._ledger_tmp.cleanup()

    def test_first_resolution_seeds_snapshot_logs_nothing(self):
        rows = config.record_state_transitions(
            "s1", {"gates": {"punctuation": "enforce"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        self.assertEqual(rows, [])
        self.assertEqual(_read_ledger(self.ledger_root), [])

    def test_real_change_logs_exactly_one_row(self):
        config.record_state_transitions(
            "s1", {"gates": {"punctuation": "enforce"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        rows = config.record_state_transitions(
            "s1", {"gates": {"punctuation": "observe"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        self.assertEqual(len(rows), 1)
        ledger = _read_ledger(self.ledger_root)
        self.assertEqual(len(ledger), 1)
        row = ledger[0]
        self.assertEqual(row["family"], "punctuation")
        self.assertEqual(row["from_state"], "enforce")
        self.assertEqual(row["to_state"], "observe")
        self.assertEqual(row["event"], "state_transition")
        self.assertEqual(row["outcome"], "")
        self.assertEqual(row["session_id"], "s1")

    def test_no_change_logs_nothing(self):
        cfg = {"gates": {"punctuation": "enforce"}}
        config.record_state_transitions("s1", cfg, state_root=self.state_root, ledger_root=self.ledger_root)
        rows = config.record_state_transitions("s1", cfg, state_root=self.state_root, ledger_root=self.ledger_root)
        self.assertEqual(rows, [])
        self.assertEqual(_read_ledger(self.ledger_root), [])

    def test_two_changed_families_log_two_rows(self):
        config.record_state_transitions(
            "s1", {"gates": {"punctuation": "enforce", "english": "enforce"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        rows = config.record_state_transitions(
            "s1", {"gates": {"punctuation": "observe", "english": "off"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["family"] for row in rows}, {"punctuation", "english"})

    def test_kill_switch_change_is_a_transition(self):
        config.record_state_transitions(
            "s1", {"gates": {"clean_code": "enforce"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        rows = config.record_state_transitions(
            "s1", {"gates": {"clean_code": "enforce"}, "kill_switches": {"clean_code": True}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["family"], "clean_code")
        self.assertEqual(rows[0]["to_state"], "off")

    def test_empty_session_id_logs_nothing(self):
        rows = config.record_state_transitions(
            "", {"gates": {"punctuation": "observe"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        self.assertEqual(rows, [])

    def test_snapshot_persists_across_invocations(self):
        config.record_state_transitions(
            "s1", {"gates": {"punctuation": "enforce"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        snapshot = session_state.read_state("s1", self.state_root).get("gate_states")
        self.assertEqual(snapshot, {family: "enforce" for family in config.GATE_FAMILIES})

    def test_concurrent_resolutions_emit_no_duplicate_rows(self):
        import threading
        config.record_state_transitions(
            "s1", {"gates": {"punctuation": "enforce"}},
            state_root=self.state_root, ledger_root=self.ledger_root,
        )
        barrier = threading.Barrier(4)
        results: list[list[dict]] = []

        def worker():
            barrier.wait()
            rows = config.record_state_transitions(
                "s1", {"gates": {"punctuation": "observe"}},
                state_root=self.state_root, ledger_root=self.ledger_root,
            )
            results.append(rows)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        total_rows = sum(len(result) for result in results)
        self.assertEqual(total_rows, 1)


class UnusableStateTests(unittest.TestCase):
    def setUp(self):
        self._state_tmp = tempfile.TemporaryDirectory()
        self._ledger_tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self._state_tmp.name)
        self.ledger_root = Path(self._ledger_tmp.name)

    def tearDown(self):
        self.state_root.chmod(0o700)
        self._state_tmp.cleanup()
        self._ledger_tmp.cleanup()

    def test_corrupt_state_does_not_crash(self):
        directory = self.state_root / "s1"
        directory.mkdir(parents=True)
        (directory / session_state.STATE_FILENAME).write_text("NOT JSON", encoding="utf-8")
        with mock.patch.object(config.sys, "stderr"):
            rows = config.record_state_transitions(
                "s1", {"gates": {"punctuation": "observe"}},
                state_root=self.state_root, ledger_root=self.ledger_root,
            )
        self.assertEqual(rows, [])

    def test_write_failure_is_swallowed(self):
        with mock.patch.object(session_state, "update_state", side_effect=PermissionError("nope")):
            with mock.patch.object(config.sys, "stderr"):
                rows = config.record_state_transitions(
                    "s1", {"gates": {"punctuation": "observe"}},
                    state_root=self.state_root, ledger_root=self.ledger_root,
                )
        self.assertEqual(rows, [])

    def test_resolution_still_usable_when_state_layer_fails(self):
        with mock.patch.object(session_state, "update_state", side_effect=PermissionError("nope")):
            with mock.patch.object(config.sys, "stderr"):
                config.record_state_transitions(
                    "s1", {"gates": {"clean_code": "observe"}},
                    state_root=self.state_root, ledger_root=self.ledger_root,
                )
        self.assertEqual(
            config.resolve_outcome(
                {"family": "clean_code", "rule": "x"},
                {"gates": {"clean_code": "observe"}},
            ),
            "would_block",
        )


class SchemaDefaultsTests(unittest.TestCase):
    def test_defaults_carry_gate_schema_keys(self):
        cfg = config.effective_config()
        self.assertEqual(cfg["gates"], {})
        self.assertEqual(cfg["kill_switches"], {})
        self.assertEqual(cfg["data_boundary"], {"enabled": False})

    def test_defaults_carry_no_key_nothing_reads(self):
        """The contract bans speculative schema, so a key with no reader must not ship."""
        self.assertNotIn("verify", config.effective_config())

    def test_baseline_defaults_to_report(self):
        self.assertEqual(config.effective_config()["baseline"], "report")

    def test_defaults_not_shared_between_calls(self):
        first = config.effective_config()
        first["gates"]["punctuation"] = "off"
        first["data_boundary"]["enabled"] = True
        second = config.effective_config()
        self.assertEqual(second["gates"], {})
        self.assertEqual(second["data_boundary"], {"enabled": False})

    def test_legacy_keys_unchanged(self):
        cfg = config.effective_config()
        self.assertTrue(cfg["punctuation"])
        self.assertTrue(cfg["english"])
        self.assertTrue(cfg["clean_code"])
        self.assertEqual(cfg["max_rows"], 8)
        self.assertEqual(cfg["exempt_paths"], [])

    def test_effective_config_merges_gate_overrides(self):
        cfg = config.effective_config({"gates": {"english": "observe"}})
        self.assertEqual(cfg["gates"]["english"], "observe")


class ProductionImportPathTests(unittest.TestCase):
    """Hook entry scripts import this module as lib.config, which is not the path the other tests use."""

    def test_transition_row_lands_when_imported_as_lib_config(self):
        hooks_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            script = (
                "import sys; sys.path.insert(0, %r)\n"
                "from lib.config import record_state_transitions\n"
                "record_state_transitions('s1', {'gates': {'punctuation': 'enforce'}},"
                " state_root=%r, ledger_root=%r)\n"
                "rows = record_state_transitions('s1', {'gates': {'punctuation': 'observe'}},"
                " state_root=%r, ledger_root=%r)\n"
                "print(len(rows))\n"
            ) % (str(hooks_dir), tmp + "/state", tmp + "/ledger", tmp + "/state", tmp + "/ledger")
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "1", result.stderr)
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()


class RuleGateTests(unittest.TestCase):
    """A single rule can hold its own state, so one lexical rule burns in without demoting its family."""

    WHAT: ClassVar[dict] = {"family": "clean_code", "rule": "what_comment"}
    DOC: ClassVar[dict] = {"family": "clean_code", "rule": "what_docstring"}
    DASH: ClassVar[dict] = {"family": "punctuation", "rule": "banned_dash"}
    HATCH: ClassVar[dict] = {"family": "clean_code", "rule": "suppression_escape_hatch"}

    def test_what_rules_ship_enforced_and_ignore_the_family_switch(self):
        for finding in (self.WHAT, self.DOC):
            self.assertEqual(config.resolve_outcome(finding, {"clean_code": False}), "block")

    def test_its_family_keeps_enforcing_around_it(self):
        self.assertEqual(config.gate_state("clean_code", {}), "enforce")
        self.assertEqual(config.resolve_outcome({"family": "clean_code", "rule": "hollow_test"}, {}), "block")

    def test_the_punctuation_rules_still_block(self):
        self.assertEqual(config.resolve_outcome(self.DASH, {}), "block")

    def test_a_rule_state_overrides_its_family(self):
        cfg = {"gates": {"punctuation": "enforce"}, "rule_gates": {"banned_dash": "observe"}}
        self.assertEqual(config.resolve_outcome(self.DASH, cfg), "would_block")

    def test_enforce_restores_blocking_for_one_rule(self):
        self.assertEqual(
            config.resolve_outcome(self.WHAT, {"rule_gates": {"what_comment": "enforce"}}), "block")

    def test_an_unknown_rule_state_falls_back_to_the_family(self):
        self.assertEqual(config.resolve_outcome(self.WHAT, {"rule_gates": {"what_comment": "sometimes"}}), "block")

    def test_a_rule_gate_cannot_release_an_always_blocking_rule(self):
        for state in ("off", "observe"):
            with self.subTest(state=state):
                cfg = {"rule_gates": {"suppression_escape_hatch": state}}
                self.assertEqual(config.resolve_outcome(self.HATCH, cfg), "block")
