"""Tests for the Stop discipline gate in stop.py."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import stop
from lib import reporting, session_state

MARKER = "craftsman" + "-ignore"


class StopGateTests(unittest.TestCase):
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

    def _payload(self, message: str, session_id: str = "s1", retry: bool = False) -> dict:
        return {
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": message,
            "stop_hook_active": retry,
        }

    def _rows(self) -> list[dict]:
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.ledger_root)

    def _decision_rows(self) -> list[dict]:
        return [row for row in self._rows() if row["event"] == "Stop"]

    def _heartbeat_rows(self) -> list[dict]:
        return [row for row in self._rows() if row["event"] == "observed"]

    def _state(self, session_id: str = "s1") -> dict:
        return session_state.read_state(session_id, self.state_root)

    def _releases(self) -> list[dict]:
        return [row for row in self._decision_rows() if row["outcome"] == "release"]


class TurnAdvanceTests(StopGateTests):
    def test_clean_message_passes_and_advances_turn(self):
        response = stop.run(self._payload("Ready for the next step."), self.cfg)
        self.assertEqual(response, {})
        state = self._state()
        self.assertEqual(state["turn_count"], 1)
        self.assertEqual(state["turn_id"], "turn-1")
        self.assertEqual(self._heartbeat_rows()[0]["turn_id"], "turn-1")

    def test_turn_advances_once_per_non_retry_stop(self):
        stop.run(self._payload("First reply."), self.cfg)
        stop.run(self._payload("Second reply."), self.cfg)
        self.assertEqual(self._state()["turn_count"], 2)
        turn_ids = [row["turn_id"] for row in self._heartbeat_rows()]
        self.assertEqual(turn_ids, ["turn-1", "turn-2"])

    def test_blocked_turn_still_advances_once(self):
        stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(self._state()["turn_count"], 1)


class GateDecisionTests(StopGateTests):
    def test_unproved_done_claim_blocks_in_default_enforce(self):
        response = stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])
        rows = self._decision_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "block")
        self.assertEqual(rows[0]["family"], "clean_code")
        self.assertEqual(rows[0]["rule"], "unproved_done_claim")

    def test_done_claim_with_evidence_passes(self):
        response = stop.run(self._payload("Fixed the parser. 3 passed via pytest."), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_transitive_fixed_claim_blocks(self):
        response = stop.run(self._payload("Fixed the parser."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])

    def test_transitive_completed_claim_blocks(self):
        response = stop.run(self._payload("Completed the implementation."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])

    def test_tests_pass_claim_blocks(self):
        response = stop.run(self._payload("Tests pass."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])

    def test_negated_run_mention_still_blocks(self):
        response = stop.run(self._payload("All done. I did not run pytest."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])

    def test_result_evidence_stands_despite_negated_mention(self):
        message = "Fixed the parser. 3 passed. I did not run the linter."
        response = stop.run(self._payload(message), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_blockquoted_evidence_does_not_count(self):
        message = "All done." + chr(10) + "> 12 passed in 0.4s"
        response = stop.run(self._payload(message), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])

    def test_fenced_runner_output_still_counts(self):
        message = "Fixed." + chr(10) + "```" + chr(10) + "12 passed" + chr(10) + "```"
        response = stop.run(self._payload(message), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_contractions_do_not_swallow_the_claim(self):
        response = stop.run(self._payload("It's done. I'd send it now."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])

    def test_quoted_done_claim_does_not_block(self):
        message = 'The user wrote "all tests pass" in the ticket, so I rechecked.'
        response = stop.run(self._payload(message), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_scanner_family_still_blocks_prose(self):
        response = stop.run(self._payload("See the notes " + chr(0x2014) + " below."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("banned_dash", response["reason"])

    def test_observe_records_would_block_without_blocking(self):
        cfg = {**self.cfg, "gates": {"clean_code": "observe"}}
        response = stop.run(self._payload("All done."), cfg)
        self.assertEqual(response, {})
        rows = self._decision_rows()
        self.assertEqual([row["outcome"] for row in rows], ["would_block"])
        self.assertEqual(rows[0]["rule"], "unproved_done_claim")

    def test_off_family_releases_without_blocking_and_ledgers_it(self):
        cfg = {**self.cfg, "gates": {"clean_code": "off"}}
        response = stop.run(self._payload("All done."), cfg)
        self.assertEqual(response, {})
        rows = self._decision_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "release")
        self.assertEqual(rows[0]["family"], "clean_code")
        self.assertEqual(rows[0]["rule"], "unproved_done_claim")

    def test_always_on_rule_blocks_even_when_families_off(self):
        cfg = {
            **self.cfg,
            "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
        }
        response = stop.run(self._payload("Flagging this " + MARKER + " case."), cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("suppression_escape_hatch", response["reason"])

    def test_empty_message_passes(self):
        response = stop.run(self._payload(""), self.cfg)
        self.assertEqual(response, {})


class RetryDedupeTests(StopGateTests):
    def test_retry_keeps_turn_id_and_writes_release_on_pass(self):
        blocked = stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(blocked["decision"], "block")
        response = stop.run(
            self._payload("Fixed the parser. 3 passed via pytest.", retry=True),
            self.cfg,
        )
        self.assertEqual(response, {})
        state = self._state()
        self.assertEqual(state["turn_count"], 1)
        self.assertEqual(state["turn_id"], "turn-1")
        release_rows = [row for row in self._releases() if row["family"] == ""]
        self.assertEqual(len(release_rows), 1)
        self.assertEqual(release_rows[0]["turn_id"], "turn-1")
        turn_ids = [row["turn_id"] for row in self._heartbeat_rows()]
        self.assertEqual(turn_ids, ["turn-1", "turn-1"])

    def test_retry_that_still_fails_blocks_again_without_release(self):
        stop.run(self._payload("All done."), self.cfg)
        response = stop.run(self._payload("It is done.", retry=True), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertEqual(self._state()["turn_count"], 1)
        outcomes = [row["outcome"] for row in self._decision_rows()]
        self.assertNotIn("release", outcomes)
        self.assertEqual(outcomes, ["block", "block"])

    def test_non_retry_pass_writes_no_release_row(self):
        stop.run(self._payload("Ready for the next step."), self.cfg)
        outcomes = [row["outcome"] for row in self._decision_rows()]
        self.assertNotIn("release", outcomes)


class ReleaseProvenanceTests(StopGateTests):
    def test_fresh_retry_without_prior_block_writes_no_release(self):
        response = stop.run(
            self._payload("Ready for the next step.", retry=True), self.cfg
        )
        self.assertEqual(response, {})
        self.assertEqual(self._releases(), [])

    def test_release_marker_is_consumed_after_first_retry_pass(self):
        stop.run(self._payload("All done."), self.cfg)
        passing = "Fixed the parser. 3 passed via pytest."
        stop.run(self._payload(passing, retry=True), self.cfg)
        self.assertEqual(len(self._releases()), 1)
        stop.run(self._payload(passing, retry=True), self.cfg)
        self.assertEqual(len(self._releases()), 1)

    def test_block_sets_marker_that_retry_pass_consumes(self):
        stop.run(self._payload("All done."), self.cfg)
        self.assertTrue(self._state().get("pending_stop_block"))
        stop.run(
            self._payload("Fixed the parser. 3 passed via pytest.", retry=True),
            self.cfg,
        )
        self.assertNotIn("pending_stop_block", self._state())


class SessionlessTests(StopGateTests):
    def test_sessionless_blocks_without_ledger_or_state(self):
        payload = self._payload("All done.")
        del payload["session_id"]
        response = stop.run(payload, self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertFalse((self.ledger_root / reporting.LEDGER_FILENAME).exists())
        self.assertFalse(self.state_root.exists())


if __name__ == "__main__":
    unittest.main()
