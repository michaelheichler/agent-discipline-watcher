"""Centralized here because five test files had reimplemented the same git and hostile-payload fixtures, and two copies had already drifted apart."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import record
from lib import reporting, session_state


def run_git(cwd: Path, *args: str) -> str:
    """Captures stdout, because the review test suite asserts on git rev-parse and diff output."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    """A local identity is required here, because git refuses to commit without one and CI has no user-level config for it."""
    run_git(path, "init", "-q")
    run_git(path, "config", "user.email", "test@example.test")
    run_git(path, "config", "user.name", "Test User")


def make_repo(root: Path) -> Path:
    """Placed under root / 'repo', because a caller still needs room to write unrelated fixtures directly under root."""
    repo = root / "repo"
    repo.mkdir()
    init_repo(repo)
    return repo


class HostileDict(dict):
    """Raises and counts on get/items, because a payload accessor that dispatches through either has a boundary hole."""

    calls = 0

    def get(self, key, default=None):
        type(self).calls += 1
        raise AssertionError("hostile get called")

    def items(self):
        type(self).calls += 1
        raise AssertionError("hostile items called")


class HostileString(str):
    """Counts __str__ calls, because an accessor that implicitly stringifies untrusted input has a boundary hole."""

    calls = 0

    def __str__(self) -> str:
        type(self).calls += 1
        return super().__str__()


class CollidingKey:
    """Hashes like 'session_id' but never compares equal, because a non-string key must never reach a documented field lookup."""

    calls = 0

    def __hash__(self):
        type(self).calls += 1
        return hash("session_id")

    def __eq__(self, other):
        type(self).calls += 1
        return False


class BatchTestCase(unittest.TestCase):
    """Shared here because BatchGateTests and BatchValidationTests each rebuilt the same isolated ledger/state harness."""

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

    def assert_block(self, response: dict, rule: str) -> str:
        self.assertEqual(response.get("decision"), "block")
        reason = response.get("reason", "")
        self.assertIsInstance(reason, str)
        self.assertTrue(reason.strip())
        self.assertIn(rule, reason)
        return reason

    def _duplicate_text(self) -> str:
        return "def duplicated(value):\n    total = value + 1\n    return total\n" * 6
