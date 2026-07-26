"""Tests for the SubagentStop discipline gate in subagent_stop.py."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import subagent_stop
import stop
from lib import done_claims, reporting, session_state

MARKER = "craftsman" + "-ignore"


class SubagentStopGateTests(unittest.TestCase):
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

    def _payload(
        self,
        message: str,
        session_id: str = "s1",
        retry: bool = False,
        transcript: str = "agent.jsonl",
        agent_id: str | None = "agent-7",
    ) -> dict:
        payload = {
            "session_id": session_id,
            "hook_event_name": "SubagentStop",
            "agent_type": "python-engineer",
            "agent_transcript_path": transcript,
            "last_assistant_message": message,
            "stop_hook_active": retry,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        return payload

    def _rows(self) -> list[dict]:
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.ledger_root)

    def _decision_rows(self) -> list[dict]:
        return [row for row in self._rows() if row["event"] == "SubagentStop"]

    def _heartbeat_rows(self) -> list[dict]:
        return [row for row in self._rows() if row["event"] == "observed"]

    def _state(self, session_id: str = "s1") -> dict:
        return session_state.read_state(session_id, self.state_root)

    def _releases(self) -> list[dict]:
        return [row for row in self._decision_rows() if row["outcome"] == "release"]


class ImportSharingTests(SubagentStopGateTests):
    def test_done_claims_scan_is_the_shared_module_object(self):
        self.assertIs(subagent_stop.scan_done_claims, done_claims.scan_done_claims)


class TurnCounterTests(SubagentStopGateTests):
    def test_clean_message_passes_without_advancing_turn(self):
        response = subagent_stop.run(self._payload("Ready for review."), self.cfg)
        self.assertEqual(response, {})
        self.assertNotIn("turn_count", self._state())
        self.assertEqual(self._heartbeat_rows()[0]["turn_id"], "")

    def test_repeated_stops_never_create_a_turn(self):
        subagent_stop.run(self._payload("First reply."), self.cfg)
        subagent_stop.run(self._payload("Second reply."), self.cfg)
        self.assertNotIn("turn_count", self._state())

    def test_heartbeat_stamps_the_turn_the_parent_stop_opened(self):
        stop.run(
            {
                "session_id": "s1",
                "hook_event_name": "Stop",
                "last_assistant_message": "Parent turn reply.",
                "stop_hook_active": False,
            },
            self.cfg,
        )
        subagent_stop.run(self._payload("Delegated reply."), self.cfg)
        rows = [
            row for row in self._heartbeat_rows() if row["hook"] == "subagent_stop"
        ]
        self.assertEqual(rows[0]["turn_id"], "turn-1")


class GateDecisionTests(SubagentStopGateTests):
    def test_unproved_done_claim_blocks_in_default_enforce(self):
        response = subagent_stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertIn("unproved_done_claim", response["reason"])
        rows = self._decision_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "block")
        self.assertEqual(rows[0]["family"], "clean_code")
        self.assertEqual(rows[0]["rule"], "unproved_done_claim")

    def test_done_claim_with_evidence_passes(self):
        response = subagent_stop.run(
            self._payload("Fixed the parser. 3 passed via pytest."), self.cfg
        )
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_scanner_family_still_blocks_prose(self):
        response = subagent_stop.run(
            self._payload("See the notes " + chr(0x2014) + " below."), self.cfg
        )
        self.assertEqual(response["decision"], "block")
        self.assertIn("banned_dash", response["reason"])

    def test_observe_records_would_block_without_blocking(self):
        cfg = {**self.cfg, "gates": {"clean_code": "observe"}}
        response = subagent_stop.run(self._payload("All done."), cfg)
        self.assertEqual(response, {})
        rows = self._decision_rows()
        self.assertEqual([row["outcome"] for row in rows], ["would_block"])
        self.assertEqual(rows[0]["rule"], "unproved_done_claim")

    def test_off_family_releases_without_blocking_and_ledgers_it(self):
        cfg = {**self.cfg, "gates": {"clean_code": "off"}}
        response = subagent_stop.run(self._payload("All done."), cfg)
        self.assertEqual(response, {})
        rows = self._decision_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "release")
        self.assertEqual(rows[0]["family"], "clean_code")

    def test_always_on_rule_blocks_even_when_families_off(self):
        cfg = {
            **self.cfg,
            "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
        }
        response = subagent_stop.run(
            self._payload("Flagging this " + MARKER + " case."), cfg
        )
        self.assertEqual(response["decision"], "block")
        self.assertIn("suppression_escape_hatch", response["reason"])

    def test_empty_message_passes(self):
        response = subagent_stop.run(self._payload(""), self.cfg)
        self.assertEqual(response, {})


class MessageOnlyScanTests(SubagentStopGateTests):
    def test_transcript_contents_are_never_scanned(self):
        transcript = self.root / "agent.jsonl"
        transcript.write_text("All done. Fixed everything.", encoding="utf-8")
        response = subagent_stop.run(
            self._payload("Ready for review.", transcript=str(transcript)),
            self.cfg,
        )
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_missing_transcript_path_is_ignored(self):
        response = subagent_stop.run(
            self._payload("Ready for review.", transcript="/nonexistent/x.jsonl"),
            self.cfg,
        )
        self.assertEqual(response, {})


class AgentAttributionTests(SubagentStopGateTests):
    def test_decision_rows_carry_agent_id_and_agent_type(self):
        subagent_stop.run(self._payload("All done."), self.cfg)
        row = self._decision_rows()[0]
        self.assertEqual(row["agent_id"], "agent-7")
        self.assertEqual(row["agent_type"], "python-engineer")
        self.assertEqual(row["hook"], "subagent_stop")

    def test_release_row_carries_agent_attribution(self):
        subagent_stop.run(self._payload("All done."), self.cfg)
        subagent_stop.run(
            self._payload("Fixed the parser. 3 passed via pytest.", retry=True),
            self.cfg,
        )
        row = self._releases()[0]
        self.assertEqual(row["agent_id"], "agent-7")
        self.assertEqual(row["agent_type"], "python-engineer")

    def test_absent_agent_fields_ledger_empty_strings(self):
        payload = self._payload("All done.")
        del payload["agent_id"]
        del payload["agent_type"]
        subagent_stop.run(payload, self.cfg)
        row = self._decision_rows()[0]
        self.assertEqual(row["agent_id"], "")
        self.assertEqual(row["agent_type"], "")


class RetryReleaseTests(SubagentStopGateTests):
    def test_block_sets_marker_that_retry_pass_consumes(self):
        subagent_stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(
            self._state()["pending_subagent_stop_block"],
            {"id:agent-7": True},
        )
        response = subagent_stop.run(
            self._payload("Fixed the parser. 3 passed via pytest.", retry=True),
            self.cfg,
        )
        self.assertEqual(response, {})
        self.assertNotIn("pending_subagent_stop_block", self._state())
        self.assertEqual(len(self._releases()), 1)

    def test_each_agent_consumes_only_its_marker(self):
        subagent_stop.run(self._payload("All done.", agent_id="A"), self.cfg)
        subagent_stop.run(self._payload("All done.", agent_id="B"), self.cfg)
        passing = "Fixed the parser. 3 passed via pytest."

        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertEqual(
            self._state()["pending_subagent_stop_block"], {"id:B": True}
        )
        self.assertEqual([row["agent_id"] for row in self._releases()], ["A"])

        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="B"), self.cfg
        )
        self.assertNotIn("pending_subagent_stop_block", self._state())
        self.assertEqual(
            [row["agent_id"] for row in self._releases()], ["A", "B"]
        )
        self.assertEqual(
            [row["family"] for row in self._releases()], ["", ""]
        )

    def test_fresh_agent_retry_cannot_consume_another_agents_marker(self):
        subagent_stop.run(self._payload("All done.", agent_id="A"), self.cfg)
        response = subagent_stop.run(
            self._payload("Ready for review.", retry=True, agent_id="B"),
            self.cfg,
        )
        self.assertEqual(response, {})
        self.assertEqual(self._releases(), [])
        self.assertEqual(
            self._state()["pending_subagent_stop_block"], {"id:A": True}
        )

    def test_retry_that_still_fails_blocks_again_without_release(self):
        subagent_stop.run(self._payload("All done."), self.cfg)
        response = subagent_stop.run(self._payload("It is done.", retry=True), self.cfg)
        self.assertEqual(response["decision"], "block")
        outcomes = [row["outcome"] for row in self._decision_rows()]
        self.assertEqual(outcomes, ["block", "block"])

    def test_marker_is_consumed_after_first_retry_pass(self):
        subagent_stop.run(self._payload("All done."), self.cfg)
        passing = "Fixed the parser. 3 passed via pytest."
        subagent_stop.run(self._payload(passing, retry=True), self.cfg)
        subagent_stop.run(self._payload(passing, retry=True), self.cfg)
        self.assertEqual(len(self._releases()), 1)

    def test_missing_agent_ids_share_documented_sentinel_slot(self):
        subagent_stop.run(
            self._payload("All done.", agent_id=None), self.cfg
        )
        subagent_stop.run(
            self._payload("It is done.", agent_id=None), self.cfg
        )
        self.assertEqual(
            self._state()["pending_subagent_stop_block"],
            {subagent_stop.UNKEYED_AGENT_KEY: True},
        )

        subagent_stop.run(
            self._payload(
                "Fixed the parser. 3 passed via pytest.",
                retry=True,
                agent_id=None,
            ),
            self.cfg,
        )
        self.assertEqual(len(self._releases()), 1)
        self.assertNotIn("pending_subagent_stop_block", self._state())

    def test_subagent_marker_does_not_touch_stop_marker(self):
        stop_payload = {
            "session_id": "s1",
            "hook_event_name": "Stop",
            "last_assistant_message": "All done.",
            "stop_hook_active": False,
        }
        stop.run(stop_payload, self.cfg)
        self.assertTrue(self._state().get("pending_stop_block"))
        subagent_stop.run(self._payload("All done."), self.cfg)
        subagent_stop.run(
            self._payload("Fixed the parser. 3 passed via pytest.", retry=True),
            self.cfg,
        )
        self.assertTrue(self._state().get("pending_stop_block"))
        self.assertNotIn("pending_subagent_stop_block", self._state())

    def test_parent_marker_survives_all_subagent_transitions(self):
        session_state.write_state(
            "s1", {"pending_stop_block": True}, self.state_root
        )
        passing = "Fixed the parser. 3 passed via pytest."
        subagent_stop.run(self._payload("All done.", agent_id="A"), self.cfg)
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="B"), self.cfg
        )
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertTrue(self._state()["pending_stop_block"])

    def test_missing_id_and_named_agent_consume_only_their_own_markers(self):
        preserved = {"pending_stop_block": True, "unrelated": {"keep": 1}}
        session_state.write_state("s1", preserved, self.state_root)
        passing = "Fixed the parser. 3 passed via pytest."

        subagent_stop.run(self._payload("All done.", agent_id=None), self.cfg)
        self.assertEqual(
            self._state(),
            {
                **preserved,
                "pending_subagent_stop_block": {
                    subagent_stop.UNKEYED_AGENT_KEY: True
                },
            },
        )

        subagent_stop.run(self._payload("All done.", agent_id="A"), self.cfg)
        self.assertEqual(
            self._state(),
            {
                **preserved,
                "pending_subagent_stop_block": {
                    subagent_stop.UNKEYED_AGENT_KEY: True,
                    "id:A": True,
                },
            },
        )

        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertEqual(
            self._state(),
            {
                **preserved,
                "pending_subagent_stop_block": {
                    subagent_stop.UNKEYED_AGENT_KEY: True
                },
            },
        )
        self.assertEqual(
            [
                (row["agent_id"], row["family"], row["rule"])
                for row in self._releases()
            ],
            [("A", "", "")],
        )

        subagent_stop.run(
            self._payload(passing, retry=True, agent_id=None), self.cfg
        )
        self.assertEqual(self._state(), preserved)
        self.assertEqual(
            [
                (row["agent_id"], row["family"], row["rule"])
                for row in self._releases()
            ],
            [("A", "", ""), ("", "", "")],
        )

    def test_second_block_cycle_emits_one_new_release(self):
        passing = "Fixed the parser. 3 passed via pytest."

        subagent_stop.run(self._payload("All done.", agent_id="A"), self.cfg)
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertEqual(
            [(row["agent_id"], row["family"]) for row in self._releases()],
            [("A", "")],
        )
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertEqual(len(self._releases()), 1)

        subagent_stop.run(self._payload("All done.", agent_id="A"), self.cfg)
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertEqual(
            [
                (row["agent_id"], row["family"], row["rule"])
                for row in self._releases()
            ],
            [("A", "", ""), ("A", "", "")],
        )
        subagent_stop.run(
            self._payload(passing, retry=True, agent_id="A"), self.cfg
        )
        self.assertEqual(len(self._releases()), 2)
        self.assertNotIn("pending_subagent_stop_block", self._state())

    def test_corrupt_pending_shapes_fail_closed_and_preserve_other_state(self):
        preserved = {"pending_stop_block": True, "unrelated": {"keep": 1}}
        passing = "Fixed the parser. 3 passed via pytest."
        corrupt_shapes = (True, "legacy-marker")

        for index, corrupt in enumerate(corrupt_shapes):
            with self.subTest(corrupt=corrupt):
                session_id = f"corrupt-{index}"
                session_state.write_state(
                    session_id,
                    {**preserved, "pending_subagent_stop_block": corrupt},
                    self.state_root,
                )
                response = subagent_stop.run(
                    self._payload(passing, session_id=session_id, retry=True),
                    self.cfg,
                )
                self.assertEqual(response, {})
                self.assertEqual(self._state(session_id), preserved)
                self.assertEqual(self._releases(), [])


class SessionlessTests(SubagentStopGateTests):
    def test_sessionless_blocks_without_ledger_or_state(self):
        payload = self._payload("All done.")
        del payload["session_id"]
        response = subagent_stop.run(payload, self.cfg)
        self.assertEqual(response["decision"], "block")
        self.assertFalse((self.ledger_root / reporting.LEDGER_FILENAME).exists())
        self.assertFalse(self.state_root.exists())


if __name__ == "__main__":
    unittest.main()
