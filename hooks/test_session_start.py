from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import session_start
import subagent_start
from lib.hookio import CONTRACT


class ReadableOutputInjectionTests(unittest.TestCase):
    def test_session_start_contains_readable_output_rules(self) -> None:
        context = session_start.run()["hookSpecificOutput"]["additionalContext"]
        self.assertIn(session_start.READABLE_OUTPUT_HEADING, context)
        expected_body = session_start._strip_frontmatter(
            session_start.READABLE_OUTPUT_SKILL.read_text(encoding="utf-8")
        ).strip()
        self.assertIn(expected_body, context)

    def test_subagent_start_does_not_contain_readable_output_rules(self) -> None:
        context = subagent_start.run()["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn(session_start.READABLE_OUTPUT_HEADING, context)
        self.assertNotIn("### 1. Lead with the next action", context)

    def test_frontmatter_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "SKILL.md"
            skill.write_text("---\nname: test\nlicense: MIT\n---\n\n# Body\n", encoding="utf-8")
            context = session_start.readable_output_context(skill)
        self.assertIn("# Body", context)
        self.assertNotIn("name: test", context)
        self.assertNotIn("license: MIT", context)

    def test_unterminated_frontmatter_returns_raw_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "SKILL.md"
            raw = "---\nname: test\n\n# Body\n"
            skill.write_text(raw, encoding="utf-8")
            context = session_start.readable_output_context(skill)
        self.assertIn(raw.strip(), context)

    def test_missing_skill_fails_open(self) -> None:
        missing = Path("/missing/readable-output/SKILL.md")
        with patch.object(session_start, "READABLE_OUTPUT_SKILL", missing):
            output = session_start.run()
        self.assertEqual(output["hookSpecificOutput"]["additionalContext"], CONTRACT)

    def test_missing_skill_logs_to_stderr(self) -> None:
        missing = Path("/missing/readable-output/SKILL.md")
        buffer = io.StringIO()
        with patch.object(session_start, "READABLE_OUTPUT_SKILL", missing), redirect_stderr(buffer):
            result = session_start.readable_output_context()
        self.assertEqual(result, "")
        self.assertIn("readable-output skill unreadable", buffer.getvalue())

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


if __name__ == "__main__":
    unittest.main()
