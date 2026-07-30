"""Tests for the Stop gate in stop.py: turn advance and heartbeat only, no message scanning."""
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

    def test_retry_does_not_advance_turn_again(self):
        stop.run(self._payload("First reply."), self.cfg)
        stop.run(self._payload("First reply, retried.", retry=True), self.cfg)
        self.assertEqual(self._state()["turn_count"], 1)


class MessageContentIsIgnoredTests(StopGateTests):
    """Chat replies are no longer scanned. Only file writes go through the discipline gates."""

    def test_banned_dash_in_message_never_blocks(self):
        response = stop.run(self._payload("See the notes " + chr(0x2014) + " below."), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_unproved_done_claim_never_blocks(self):
        response = stop.run(self._payload("All done."), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_suppression_marker_in_message_never_blocks(self):
        response = stop.run(self._payload("Flagging this " + MARKER + " case."), self.cfg)
        self.assertEqual(response, {})
        self.assertEqual(self._decision_rows(), [])

    def test_empty_message_passes(self):
        response = stop.run(self._payload(""), self.cfg)
        self.assertEqual(response, {})


class SessionlessTests(StopGateTests):
    def test_sessionless_never_blocks_and_writes_no_ledger_or_state(self):
        payload = self._payload("All done.")
        del payload["session_id"]
        response = stop.run(payload, self.cfg)
        self.assertEqual(response, {})
        self.assertFalse((self.ledger_root / reporting.LEDGER_FILENAME).exists())
        self.assertFalse(self.state_root.exists())


if __name__ == "__main__":
    unittest.main()
