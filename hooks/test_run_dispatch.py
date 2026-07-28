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
    "UserPromptSubmit": "prompt_submit.py",
    "PreToolUse": "pre_write.py",
    "PreCommit": "pre_commit.py",
    "PreBash": "pre_bash.py",
    "PreMcp": "pre_mcp.py",
    "PostToolUse": "record.py",
    "PostToolBatch": "batch.py",
    "PostToolUseFailure": "failure.py",
    "SubagentStop": "subagent_stop.py",
    "Stop": "stop.py",
}

EXPECTED_USAGE = "usage: run.sh " + "|".join(DISPATCH)

# The stub answers only through PATH resolution, because an absolute interpreter would run the real hook and drop this marker.
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
            check=False,
        )

    def test_routes_each_event_to_its_entry_script(self):
        for event, script in DISPATCH.items():
            with self.subTest(event=event):
                result = self._run(event)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith(STUB_MARKER), result.stdout)
                self.assertTrue(result.stdout.strip().endswith(script), result.stdout)

    def test_every_dispatched_script_exists(self):
        for event, script in DISPATCH.items():
            with self.subTest(event=event):
                self.assertTrue((ROOT / "hooks" / script).is_file(), f"{event} routes to a missing {script}")

    def test_no_event_routes_to_an_empty_script(self):
        dispatch = RUN_SH.read_text(encoding="utf-8").split('DISPATCH="', 1)[1].split('"', 1)[0]
        pairs = dict(pair.split(":", 1) for pair in dispatch.split())
        self.assertEqual(pairs, DISPATCH)
        for event, script in pairs.items():
            self.assertTrue(script, f"{event} is registered but routes nowhere")

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
