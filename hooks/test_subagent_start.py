"""SubagentStart tests, because a subagent gets exactly one shot at this context and a silent failure here leaves it writing blind."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import subagent_start
from lib.hookio import CONTRACT_MAX_CHARS

RUN_SH = Path(__file__).parent / "run.sh"


def injected(payload: dict | None) -> dict:
    return subagent_start.run(payload)["hookSpecificOutput"]


class SubagentStartInjectionTests(unittest.TestCase):
    def test_context_arrives_on_the_model_channel_under_the_right_event(self) -> None:
        block = injected({})
        self.assertEqual(block["hookEventName"], "SubagentStart")
        self.assertIn("additionalContext", block)

    def test_precedence_over_the_agent_definition_is_stated(self) -> None:
        self.assertIn("override the agent definition", injected({})["additionalContext"])

    def test_the_real_contract_ships_rather_than_a_one_line_reminder(self) -> None:
        text = injected({})["additionalContext"]
        for clause in ("em dash", "possessive pronoun", "hollow test", "Every finding blocks",
                       "Craftsman suppression marker", "empty intensifiers"):
            with self.subTest(clause=clause):
                self.assertIn(clause, text)

    def test_the_injected_string_respects_its_cap(self) -> None:
        self.assertLessEqual(len(injected({})["additionalContext"]), CONTRACT_MAX_CHARS)

    def test_no_payload_shape_makes_the_hook_raise(self) -> None:
        for payload in (None, {}, {"agent_type": "code-reviewer"}, {"session_id": None}):
            with self.subTest(payload=payload):
                self.assertEqual(injected(payload)["hookEventName"], "SubagentStart")


class SubagentStartProcessTests(unittest.TestCase):
    def _run(self, stdin: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(RUN_SH), "SubagentStart"], input=stdin, text=True,
            capture_output=True, check=False,
        )

    def test_run_sh_routes_the_event_and_emits_the_context(self) -> None:
        result = self._run(json.dumps({"agent_type": "Explore"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        block = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(block["hookEventName"], "SubagentStart")
        self.assertIn("Agent Discipline Watcher contract", block["additionalContext"])

    def test_malformed_stdin_still_yields_the_contract(self) -> None:
        result = self._run("{not json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SubagentStart",
        )


if __name__ == "__main__":
    unittest.main()
