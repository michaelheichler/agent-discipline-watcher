"""Tests for the SubagentStop gate in subagent_stop.py: heartbeat only, no message scanning."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import subagent_stop
import stop
from lib import reporting, session_state

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

    def _payload(self, message: str, session_id: str = "s1") -> dict:
        return {
            "session_id": session_id,
            "hook_event_name": "SubagentStop",
            "agent_type": "python-engineer",
            "agent_id": "agent-7",
            "last_assistant_message": message,
            "stop_hook_active": False,
        }

    def _rows(self) -> list[dict]:
        return reporting._read_jsonl(reporting.LEDGER_FILENAME, self.ledger_root)

    def _heartbeat_rows(self) -> list[dict]:
        return [row for row in self._rows() if row["event"] == "observed"]

    def _state(self, session_id: str = "s1") -> dict:
        return session_state.read_state(session_id, self.state_root)


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


class MessageContentIsIgnoredTests(SubagentStopGateTests):
    """Chat replies are no longer scanned. Only file writes go through the discipline gates."""

    def test_banned_dash_in_message_never_blocks(self):
        response = subagent_stop.run(
            self._payload("See the notes " + chr(0x2014) + " below."), self.cfg
        )
        self.assertEqual(response, {})

    def test_unproved_done_claim_never_blocks(self):
        response = subagent_stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(response, {})

    def test_suppression_marker_in_message_never_blocks(self):
        response = subagent_stop.run(
            self._payload("Flagging this " + MARKER + " case."), self.cfg
        )
        self.assertEqual(response, {})

    def test_empty_message_passes(self):
        response = subagent_stop.run(self._payload(""), self.cfg)
        self.assertEqual(response, {})


class SessionlessTests(SubagentStopGateTests):
    def test_sessionless_never_blocks_and_writes_no_ledger_or_state(self):
        payload = self._payload("All done.")
        del payload["session_id"]
        response = subagent_stop.run(payload, self.cfg)
        self.assertEqual(response, {})
        self.assertFalse((self.ledger_root / reporting.LEDGER_FILENAME).exists())
        self.assertFalse(self.state_root.exists())


if __name__ == "__main__":
    unittest.main()
