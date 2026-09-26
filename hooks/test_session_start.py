from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import session_start


class SessionStartLifecycleTests(unittest.TestCase):
    def test_session_start_runs_retention_and_acquires_a_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"state_root": str(root / "state"), "ledger_root": str(root / "ledger")}
            with patch("session_start.retention.sweep") as sweep:
                session_start.run({"session_id": "s1"}, config)

            sweep.assert_called_once()
            self.assertEqual(
                session_start.session_state.live_session_ids(config["state_root"]), frozenset({"s1"})
            )

    def test_resumed_old_session_is_protected_before_startup_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            session = state_root / "s1"
            session.mkdir(parents=True)
            (session / "state.json").write_text("{}", encoding="utf-8")
            stale = time.time() - 31 * 24 * 60 * 60
            os.utime(session, (stale, stale))

            session_start.run({"session_id": "s1"}, {"state_root": str(state_root)})

            self.assertTrue(session.exists())

    def test_startup_cleanup_is_idempotent_for_the_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"state_root": str(root / "state"), "ledger_root": str(root / "ledger")}
            session = root / "state" / "s1"
            session.mkdir(parents=True)
            (session / "state.json").write_text("{}", encoding="utf-8")
            stale = time.time() - 31 * 24 * 60 * 60
            os.utime(session, (stale, stale))

            session_start.run({"session_id": "s1"}, config)
            session_start.run({"session_id": "s1"}, config)

            self.assertTrue(session.exists())
            self.assertEqual(session_start.session_state.live_session_ids(config["state_root"]), frozenset({"s1"}))


def _context(source: str | None) -> str:
    payload = {} if source is None else {"source": source}
    return session_start.run(payload)["hookSpecificOutput"]["additionalContext"]


class SessionStartContractTests(unittest.TestCase):
    def test_startup_and_an_unknown_source_get_the_full_contract(self) -> None:
        for source in ("startup", None, "unexpected"):
            with self.subTest(source=source):
                self.assertEqual(_context(source), session_start.CONTRACT)

    def test_resume_clear_and_compact_get_one_line(self) -> None:
        for source in ("resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertEqual(_context(source), (
                    "ADW is active. Fix each named file and line, then retry the blocked action. "
                    "Do not disable the gate or delete its state."
                ))


if __name__ == "__main__":
    unittest.main()
