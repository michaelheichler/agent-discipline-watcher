from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import session_start
import subagent_start
from lib.hookio import CONTRACT


class ReadableOutputInjectionTests(unittest.TestCase):
    def test_session_start_contains_readable_output_rules(self) -> None:
        context = session_start.run()["hookSpecificOutput"]["additionalContext"]
        self.assertIn(session_start.READABLE_OUTPUT_HEADING, context)
        self.assertIn("### 10. No preamble, no recap, no closing pleasantries", context)

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

    def test_missing_skill_fails_open(self) -> None:
        missing = Path("/missing/readable-output/SKILL.md")
        with patch.object(session_start, "READABLE_OUTPUT_SKILL", missing):
            output = session_start.run()
        self.assertEqual(output["hookSpecificOutput"]["additionalContext"], CONTRACT)


if __name__ == "__main__":
    unittest.main()
