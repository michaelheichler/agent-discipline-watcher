"""No sequence of tool calls may end with a self-protection rule suppressed, and no config may crash a gate open."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pre_bash
import pre_mcp
import pre_tool
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
ENTRY_POINTS = ("pre_write.py", "pre_bash.py", "pre_mcp.py", "record.py", "pre_commit.py", "batch.py")
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

    def _apply_patch(self, patch: str, config: dict | None = None) -> dict:
        payload = {
            "session_id": "s1", "cwd": str(self.root),
            "tool_name": "apply_patch",
            "tool_input": {"command": ["apply_patch", patch]},
        }
        return pre_write.run(payload, {**self.cfg, **(config or {})})

    def test_a_heredoc_that_grants_the_escape_is_blocked(self):
        command = "cat > " + str(self.config) + " <<'JE'\n" + GRANT + "\nJE\n"
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_an_echo_redirect_that_grants_the_escape_is_blocked(self):
        command = "echo '" + GRANT + "' > " + str(self.config)
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_a_heredoc_that_downgrades_an_always_blocking_rule_is_blocked(self):
        command = "cat > " + str(self.config) + " <<'JE'\n" + DOWNGRADE + "\nJE\n"
        self.assertIn("self_protection/config_seal", self._blocked(self._bash(command)))

    def test_a_heredoc_that_downgrades_a_bash_write_rule_is_blocked(self):
        for rule in (
            "inline_interpreter_write", "shell_payload_block", "interpreter_heredoc_write",
            "dynamic_heredoc_write", "decode_pipe_write", "inplace_edit_write", "opaque_source_write",
        ):
            with self.subTest(rule=rule):
                downgrade = json.dumps({"rule_gates": {rule: "off"}})
                command = "cat > " + str(self.config) + " <<'JE'\n" + downgrade + "\nJE\n"
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

    def test_a_delete_file_patch_against_a_protected_path_is_blocked(self):
        self.config.write_text("{}", encoding="utf-8")
        patch = "*** Begin Patch\n*** Delete File: " + str(self.config) + "\n*** End Patch"
        self.assertIn("self_protection/config_seal", self._blocked(self._apply_patch(patch)))

    def test_a_deletion_only_update_patch_against_a_protected_path_is_blocked(self):
        self.config.write_text("{}", encoding="utf-8")
        patch = (
            "*** Begin Patch\n*** Update File: " + str(self.config) + "\n"
            "@@\n-{}\n*** End Patch"
        )
        self.assertIn("self_protection/config_seal", self._blocked(self._apply_patch(patch)))

    def test_an_ordinary_apply_patch_is_unaffected(self):
        target = self.root / "ok.py"
        patch = "*** Begin Patch\n*** Add File: " + str(target) + "\n+x = 1\n*** End Patch"
        self.assertEqual(self._apply_patch(patch), {})

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

    def test_a_shell_write_to_the_watcher_install_is_blocked_by_path(self):
        target = self.root / "home" / ".claude" / "skills" / "agent-discipline-watcher" / "SKILL.md"
        command = "echo '{}' > " + str(target)
        findings = pre_bash.target_findings(command, None, self.root / "home")
        self.assertEqual([row["rule"] for row in findings], ["watcher_install_surface"])

    def test_a_shell_write_to_another_skill_is_left_to_host_permissions(self):
        target = self.root / "home" / ".claude" / "skills" / "humanizer-de" / "SKILL.md"
        command = "echo '{}' > " + str(target)
        self.assertEqual(pre_bash.target_findings(command, None, self.root / "home"), [])

    def test_an_ordinary_shell_write_stays_allowed(self):
        self.assertEqual(self._bash("echo 'x = 1' > " + str(self.root / "ok.py")), {})

    def _mcp(self, tool_input: dict, config: dict | None = None) -> dict:
        payload = {
            "session_id": "s1", "cwd": str(self.root), "tool_name": "mcp__fs__write_file",
            "tool_input": tool_input,
        }
        return pre_mcp.run(payload, {**self.cfg, **(config or {})})

    def test_an_mcp_write_to_an_existing_gate_config_is_blocked_via_path(self):
        self.config.write_text("{}", encoding="utf-8")
        self.assertIn("self_protection/config_seal", self._blocked(self._mcp({"path": str(self.config)})))
        self.assertEqual(self.config.read_text(encoding="utf-8"), "{}")

    def test_an_mcp_write_to_an_existing_gate_config_is_blocked_via_file_path(self):
        self.config.write_text("{}", encoding="utf-8")
        self.assertIn(
            "self_protection/config_seal", self._blocked(self._mcp({"file_path": str(self.config)}))
        )

    def test_an_mcp_write_using_relative_path_resolves_against_cwd(self):
        self.config.write_text("{}", encoding="utf-8")
        self.assertIn(
            "self_protection/config_seal", self._blocked(self._mcp({"relative_path": CONFIG_NAME}))
        )

    def test_an_mcp_write_targeting_a_paths_list_is_blocked(self):
        self.config.write_text("{}", encoding="utf-8")
        other = self.root / "ok.py"
        response = self._mcp({"paths": [str(other), str(self.config)]})
        self.assertIn("self_protection/config_seal", self._blocked(response))

    def test_an_mcp_write_to_watcher_state_is_blocked(self):
        target = Path.home() / ".adw" / "state" / "s1" / "state.json"
        self.assertIn("self_protection/state_mutation", self._blocked(self._mcp({"path": str(target)})))

    def test_an_mcp_write_to_the_legacy_state_home_is_blocked(self):
        """The legacy root stays guarded because an unmigrated machine still keeps its state there."""
        target = Path.home() / ".agent-discipline" / "state" / "s1" / "state.json"
        self.assertIn("self_protection/state_mutation", self._blocked(self._mcp({"path": str(target)})))

    def test_an_mcp_write_to_the_watcher_install_is_blocked_by_path(self):
        target = Path.home() / ".claude" / "skills" / "agent-discipline-watcher" / "SKILL.md"
        self.assertIn(
            "self_protection/watcher_install_surface", self._blocked(self._mcp({"path": str(target)}))
        )

    def test_an_ordinary_mcp_write_stays_allowed(self):
        self.assertEqual(self._mcp({"path": str(self.root / "ok.py")}), {})

    def test_an_mcp_write_without_a_session_id_still_blocks_a_protected_path(self):
        self.config.write_text("{}", encoding="utf-8")
        payload = {
            "cwd": str(self.root), "tool_name": "mcp__fs__write_file",
            "tool_input": {"path": str(self.config)},
        }
        response = pre_mcp.run(payload, self.cfg)
        self.assertEqual(
            response["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_an_mcp_gate_crash_still_blocks_a_protected_path(self):
        self.config.write_text("{}", encoding="utf-8")
        with mock.patch.object(pre_mcp, "normalize_payload", side_effect=RuntimeError("boom")):
            response = self._mcp({"path": str(self.config)})
        self.assertEqual(
            response["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_an_mcp_write_planting_an_escape_config_is_blocked_by_content(self):
        target = self.root / "sub" / CONFIG_NAME
        response = self._mcp({"path": str(target), "content": '{"state_root": "/tmp/steal"}'})
        self.assertIn("self_protection", self._blocked(response))

    def test_a_decoy_field_does_not_hide_an_escape_payload_in_another_field(self):
        target = self.root / "sub" / CONFIG_NAME
        response = self._mcp({
            "path": str(target),
            "text": "not json at all",
            "content": '{"state_root": "/tmp/steal"}',
        })
        self.assertIn("self_protection", self._blocked(response))

    def test_an_mcp_write_to_the_gate_config_is_blocked_through_the_pretool_dispatcher(self):
        self.config.write_text("{}", encoding="utf-8")
        payload = {
            "session_id": "s1", "cwd": str(self.root), "tool_name": "mcp__fs__write_file",
            "tool_input": {"path": str(self.config)},
        }
        self.assertIn("self_protection/config_seal", self._blocked(pre_tool.run(payload, self.cfg)))


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

    def _assert_deferred_work_block(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertNotIn("decision", response)
        self.assertIn("deferred_work_comment", response["hookSpecificOutput"]["additionalContext"])

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
            self.target.write_text(MARKER, encoding="utf-8")
            with self.subTest(config=malformed):
                self._assert_deferred_work_block(self._run("record.py"))

    def test_unparseable_config_text_falls_back_to_the_enforcing_defaults(self):
        (self.root / CONFIG_NAME).write_text("{not json", encoding="utf-8")
        self._assert_deferred_work_block(self._run("record.py"))


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
