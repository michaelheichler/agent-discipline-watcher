"""Subprocess tests for hooks/run.sh event dispatch."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "hooks" / "run.sh"

DISPATCH = {
    "SessionStart": "session_start.py",
    "PreToolUse": "pre_write.py",
    "PreCommit": "pre_commit.py",
    "PostToolUse": "record.py",
}

EXPECTED_USAGE = "usage: run.sh " + "|".join(list(DISPATCH) + ["Stop"])

# The stub answers only when run.sh resolves its interpreter through PATH, so hardcoding an
# absolute interpreter would run the real hook and drop this marker instead of passing quietly.
STUB_MARKER = "adw-stub"


class RunDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        stub = Path(self.tmp.name) / "python3"
        stub.write_text(f'#!/bin/sh\necho "{STUB_MARKER} $@"\n')
        stub.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = self.tmp.name + os.pathsep + env.get("PATH", "")
        self.env = env

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [str(RUN_SH), *args],
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_routes_each_event_to_its_entry_script(self):
        for event, script in DISPATCH.items():
            with self.subTest(event=event):
                result = self._run(event)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith(STUB_MARKER), result.stdout)
                self.assertTrue(result.stdout.strip().endswith(script), result.stdout)

    def test_stop_is_a_wired_no_op(self):
        result = self._run("Stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unknown_event_exits_2_and_names_supported_events(self):
        result = self._run("Nope")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip(), EXPECTED_USAGE)

    def test_missing_event_exits_2(self):
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip(), EXPECTED_USAGE)


if __name__ == "__main__":
    unittest.main()
