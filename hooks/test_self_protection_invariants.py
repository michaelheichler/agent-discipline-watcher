"""No sequence of tool calls may end with a self-protection rule suppressed, and no config may crash a gate open."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pre_bash
import pre_write
from lib import protected
from lib.config import CONFIG_NAME
from lib.scanner import scan_all

HOOKS = Path(__file__).resolve().parent
GRANT = json.dumps({protected.AUTH_KEY: True})
DOWNGRADE = json.dumps({"rule_gates": {"suppression_escape_hatch": "off"}})
ATTACK = json.dumps({
    "punctuation": False,
    "english": False,
    "clean_code": False,
    "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
    "state_root": "/tmp/attacker-state",
    "ledger_root": "/tmp/attacker-ledger",
})
# Deferred because the discipline scanner would otherwise flag this test file.
MARKER = "# " + ("TO" + "DO") + " later\nx = 1\n"
ENTRY_POINTS = ("pre_write.py", "pre_bash.py", "record.py", "pre_commit.py", "batch.py")
MALFORMED = (
    {"gates": ["off"]},
    {"gates": "off"},
    {"gates": 5},
    {"gates": True},
    {"kill_switches": ["clean_code"]},
    {"kill_switches": "clean_code"},
    {"kill_switches": 0.5},
    {"rule_gates": ["off"]},
    {"rule_gates": "off"},
    {"rule_gates": 7},
    {"exempt_paths": 5},
    {"exempt_paths": True},
    {"exempt_families": 3},
    {"gates": {"clean_code": ["off"]}},
)


class SelfGrantChainTests(unittest.TestCase):
    """Every route an agent has to the gate config, walked end to end, must end in a block."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.config = self.root / CONFIG_NAME
        self.cfg = {
            "ledger_root": str(self.root / "ledger"),
            "state_root": str(self.root / "state"),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _bash(self, command: str, config: dict | None = None) -> dict:
        payload = {"session_id": "s1", "cwd": str(self.root), "tool_input": {"command": command}}
        return pre_bash.run(payload, {**self.cfg, **(config or {})})

    def _write(self, content: str, config: dict | None = None) -> dict:
        payload = {
            "session_id": "s1", "cwd": str(self.root),
            "tool_input": {"file_path": str(self.config), "content": content},
        }
        return pre_write.run(payload, {**self.cfg, **(config or {})})

    def _blocked(self, response: dict) -> str:
        self.assertEqual(response.get("decision"), "block", response)
        return response["reason"]

    def test_a_heredoc_that_grants_the_escape_is_blocked(self):
        command = "cat > " + str(self.config) + " <<'JE'\n" + GRANT + "\nJE\n"
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_an_echo_redirect_that_grants_the_escape_is_blocked(self):
        command = "echo '" + GRANT + "' > " + str(self.config)
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_a_heredoc_that_downgrades_an_always_blocking_rule_is_blocked(self):
        command = "cat > " + str(self.config) + " <<'JE'\n" + DOWNGRADE + "\nJE\n"
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_a_write_that_grants_the_escape_is_blocked_before_the_file_exists(self):
        self.assertIn("self_protection/config_seal", self._blocked(self._write(GRANT)))
        self.assertFalse(self.config.exists())

    def test_an_attack_config_cannot_be_created_without_a_finding(self):
        self.assertIn("self_protection/config_seal", self._blocked(self._write(ATTACK)))
        self.assertFalse(self.config.exists())

    def test_an_opaque_shell_write_to_an_existing_config_is_blocked(self):
        self.config.write_text("{}", encoding="utf-8")
        command = "cp /tmp/other.json " + str(self.config)
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_a_landed_grant_cannot_authorize_the_next_grant(self):
        self.config.write_text(GRANT, encoding="utf-8")
        granted = {protected.AUTH_KEY: True}
        self.assertIn("self_protection/config_seal", self._blocked(self._write(GRANT, granted)))
        command = "cat > " + str(self.config) + " <<'JE'\n" + GRANT + "\nJE\n"
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command, granted)))

    def test_a_landed_grant_is_inert_against_the_rest_of_the_family(self):
        self.config.write_text(GRANT, encoding="utf-8")
        granted = {protected.AUTH_KEY: True}
        for command, rule in (
            ("git commit --no-verify -m x", "commit_gate_bypass"),
            ("rm -f " + str(self.config), "state_deletion"),
        ):
            with self.subTest(command=command):
                self.assertIn("self_protection/" + rule, self._blocked(self._bash(command, granted)))

    def test_setting_the_escape_variable_inline_is_still_a_cap_override(self):
        command = protected.AUTH_ENV + "=1 python3 build.py"
        self.assertIn("self_protection/cap_override", self._blocked(self._bash(command)))

    def test_a_shell_write_to_a_live_client_surface_is_blocked_by_path(self):
        target = self.root / "home" / ".claude" / "settings.json"
        command = "echo '{}' > " + str(target)
        findings = pre_bash.target_findings(command, None, self.root / "home")
        self.assertEqual([row["rule"] for row in findings], ["live_client_surface"])

    def test_an_ordinary_shell_write_stays_allowed(self):
        self.assertEqual(self._bash("echo 'x = 1' > " + str(self.root / "ok.py")), {})


class MalformedConfigFailClosedTests(unittest.TestCase):
    """A gate that cannot read its config must fail closed, because exit one reads as hook error and lets the call through."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.target = self.root / "legacy.py"
        self.target.write_text(MARKER, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self) -> str:
        return json.dumps({
            "session_id": "s1", "cwd": str(self.root), "tool_name": "Write",
            "tool_input": {
                "file_path": str(self.target), "content": MARKER, "command": "git commit -m msg",
            },
            "tool_calls": [{"tool_name": "Write", "tool_input": {"file_path": str(self.target)}}],
        })

    def _run(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOKS / script)], input=self._payload(), text=True,
            capture_output=True, check=False, cwd=str(self.root),
        )

    def test_no_entry_point_dies_on_a_malformed_gate_map(self):
        for malformed in MALFORMED:
            (self.root / CONFIG_NAME).write_text(json.dumps(malformed), encoding="utf-8")
            for script in ENTRY_POINTS:
                result = self._run(script)
                with self.subTest(config=malformed, script=script):
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIn(result.returncode, (0, 2), result.stderr)
                    if result.returncode == 0:
                        json.loads(result.stdout or "{}")

    def test_a_malformed_gate_map_does_not_release_the_finding(self):
        for malformed in MALFORMED:
            (self.root / CONFIG_NAME).write_text(json.dumps(malformed), encoding="utf-8")
            with self.subTest(config=malformed):
                self.assertEqual(self._run("record.py").returncode, 2)

    def test_unparseable_config_text_falls_back_to_the_enforcing_defaults(self):
        (self.root / CONFIG_NAME).write_text("{not json", encoding="utf-8")
        self.assertEqual(self._run("record.py").returncode, 2)


class ExemptionDegradeTests(unittest.TestCase):
    """A malformed exemption must scan more, never less, so a typo cannot silence a surface."""

    def test_a_malformed_exempt_paths_still_scans(self):
        for malformed in (5, True, "a.py", {"a.py": True}, None):
            with self.subTest(value=malformed):
                findings = scan_all("a.py", MARKER, {"exempt_paths": malformed})
                self.assertIn("deferred_work_comment", [row["rule"] for row in findings])

    def test_a_well_formed_exempt_paths_list_still_exempts(self):
        findings = scan_all("a.py", MARKER, {"exempt_paths": ["a.py"]})
        self.assertNotIn("deferred_work_comment", [row["rule"] for row in findings])

    def test_a_malformed_exempt_families_still_scans(self):
        for malformed in (3, "clean_code", ["clean_code"], {"a.py": "clean_code"}):
            with self.subTest(value=malformed):
                findings = scan_all("a.py", MARKER, {"exempt_families": malformed})
                self.assertIn("deferred_work_comment", [row["rule"] for row in findings])


if __name__ == "__main__":
    unittest.main()
