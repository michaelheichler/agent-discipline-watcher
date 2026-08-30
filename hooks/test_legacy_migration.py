"""Legacy migration tests: removing path-based watcher wiring keeps unrelated settings and repeats without drift."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MERGE = ROOT / "hooks" / "merge-claude-settings.py"
INSTALL = ROOT / "install.sh"
CHECKOUT = "/tmp/agent-discipline-watcher"  # noqa: S108 (placeholder path, never created)

LEGACY_SETTINGS = {
    "model": "claude-opus-5",
    "permissions": {"allow": ["Bash(git status)"]},
    "hooks": {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": f"{CHECKOUT}/hooks/run.sh SessionStart"}]},
            {"hooks": [{"type": "command", "command": "python /x/unrelated-start.py"}]},
        ],
        "PreToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [{"type": "command", "command": f"{CHECKOUT}/hooks/run.sh PreToolUse"}],
            }
        ],
        "Stop": [{"hooks": [{"type": "command", "command": f"{CHECKOUT}/hooks/run.sh Stop"}]}],
        "Notification": [{"hooks": [{"type": "command", "command": "python /x/notify.py"}]}],
    },
}


def run_merge(settings: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MERGE), "--settings", str(settings), *args],
        capture_output=True, text=True, check=True,
    )


class LegacyRemovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Path(self.tmp.name) / "settings.json"
        self.settings.write_text(json.dumps(LEGACY_SETTINGS, indent=2), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def migrate(self) -> dict:
        run_merge(self.settings, "--remove-legacy")
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_every_watcher_entry_is_removed(self):
        merged = self.migrate()
        self.assertNotIn("agent-discipline-watcher", json.dumps(merged))
        self.assertNotIn("run.sh", json.dumps(merged))

    def test_unrelated_settings_survive_untouched(self):
        merged = self.migrate()
        self.assertEqual(merged["model"], LEGACY_SETTINGS["model"])
        self.assertEqual(merged["permissions"], LEGACY_SETTINGS["permissions"])
        self.assertEqual(merged["hooks"]["Notification"], LEGACY_SETTINGS["hooks"]["Notification"])
        self.assertIn("unrelated-start.py", json.dumps(merged["hooks"]["SessionStart"]))

    def test_lifecycles_emptied_by_the_removal_are_dropped(self):
        merged = self.migrate()
        self.assertNotIn("Stop", merged["hooks"])
        self.assertNotIn("PreToolUse", merged["hooks"])
        self.assertIn("SessionStart", merged["hooks"])

    def test_migration_is_idempotent(self):
        first = self.settings.read_text(encoding="utf-8")
        self.migrate()
        once = self.settings.read_text(encoding="utf-8")
        self.migrate()
        twice = self.settings.read_text(encoding="utf-8")
        self.assertNotEqual(first, once)
        self.assertEqual(once, twice, "a second migration must change nothing")

    def test_clean_settings_are_left_alone(self):
        clean = {"model": "claude-opus-5", "hooks": {"Notification": [
            {"hooks": [{"type": "command", "command": "python /x/notify.py"}]}
        ]}}
        self.settings.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        before = self.settings.read_text(encoding="utf-8")
        run_merge(self.settings, "--remove-legacy")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), before)

    def test_user_authored_empty_lifecycle_is_preserved(self):
        payload = {"hooks": {"Stop": [], "SessionStart": [
            {"hooks": [{"type": "command", "command": f"{CHECKOUT}/hooks/run.sh SessionStart"}]}
        ]}}
        self.settings.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        merged = self.migrate()
        self.assertIn("Stop", merged["hooks"], "an empty lifecycle the user wrote is not ours to delete")
        self.assertNotIn("SessionStart", merged["hooks"])

    def test_missing_settings_file_is_a_no_op(self):
        target = Path(self.tmp.name) / "absent.json"
        run_merge(target, "--remove-legacy")
        self.assertFalse(target.exists(), "migration must not create a settings file that was never there")

    def test_skill_dir_is_required_without_the_removal_flag(self):
        result = subprocess.run(
            [sys.executable, str(MERGE), "--settings", str(self.settings)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--skill-dir is required", result.stderr)


class InstallScriptTests(unittest.TestCase):
    def test_default_claude_branch_prints_the_plugin_commands(self):
        with tempfile.TemporaryDirectory() as home:
            settings = Path(home) / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps(LEGACY_SETTINGS), encoding="utf-8")
            result = subprocess.run(
                ["bash", str(INSTALL), "--claude"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertIn("/plugin marketplace add", result.stdout)
            self.assertIn("/plugin install agent-discipline-watcher@", result.stdout)
            self.assertNotIn("agent-discipline-watcher/hooks/run.sh", settings.read_text(encoding="utf-8"))

    def test_legacy_flag_still_writes_path_based_wiring(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                ["bash", str(INSTALL), "--claude-legacy"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertIn("legacy path-based wiring", result.stdout)
            settings = json.loads((Path(home) / ".claude" / "settings.json").read_text(encoding="utf-8"))
            self.assertRegex(json.dumps(settings), r'run\.sh\\?"?\s*PreToolUse')

    def test_default_claude_branch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as home:
            settings = Path(home) / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps(LEGACY_SETTINGS), encoding="utf-8")
            args = ["bash", str(INSTALL), "--claude"]
            env = {"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"}
            subprocess.run(args, capture_output=True, text=True, check=True, env=env)
            once = settings.read_text(encoding="utf-8")
            subprocess.run(args, capture_output=True, text=True, check=True, env=env)
            self.assertEqual(settings.read_text(encoding="utf-8"), once)

    def test_codex_only_flag_does_not_also_run_the_claude_branch(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                ["bash", str(INSTALL), "--codex"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertNotIn("/plugin marketplace add", result.stdout)
            self.assertFalse((Path(home) / ".claude" / "settings.json").exists())
            self.assertTrue((Path(home) / ".codex" / "config.toml").exists())

    def test_claude_only_flag_does_not_also_run_the_codex_branch(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                ["bash", str(INSTALL), "--claude"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertIn("/plugin marketplace add", result.stdout)
            self.assertFalse((Path(home) / ".codex" / "config.toml").exists())

    def test_claude_only_flag_does_not_also_run_the_omp_branch(self):
        with tempfile.TemporaryDirectory() as home:
            subprocess.run(
                ["bash", str(INSTALL), "--claude"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertFalse((Path(home) / ".omp" / "agent" / "settings.json").exists())

    def test_omp_only_flag_does_not_also_run_the_claude_or_codex_branch(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                ["bash", str(INSTALL), "--omp"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertNotIn("/plugin marketplace add", result.stdout)
            self.assertFalse((Path(home) / ".claude" / "settings.json").exists())
            self.assertFalse((Path(home) / ".codex" / "config.toml").exists())
            self.assertTrue((Path(home) / ".omp" / "agent" / "settings.json").exists())

    def test_omp_flag_registers_the_extension_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as home:
            args = ["bash", str(INSTALL), "--omp"]
            env = {"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"}
            settings = Path(home) / ".omp" / "agent" / "settings.json"
            subprocess.run(args, capture_output=True, text=True, check=True, env=env)
            once = json.loads(settings.read_text(encoding="utf-8"))
            extension_path = str((Path(home) / ".adw" / "install" / "agent-discipline-watcher" / "pi" / "extensions" / "agent-discipline-watcher" / "index.ts").resolve())
            self.assertEqual(once["extensions"], [extension_path])
            subprocess.run(args, capture_output=True, text=True, check=True, env=env)
            twice = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(once, twice, "a second install must not duplicate the extension entry")

    def test_omp_agent_dir_honors_pi_coding_agent_dir_override(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as agent_dir:
            subprocess.run(
                ["bash", str(INSTALL), "--omp"],
                capture_output=True, text=True, check=True,
                env={
                    "HOME": home, "PATH": _path(),
                    "PI_CODING_AGENT_DIR": agent_dir, "ADW_SKIP_PLUGIN": "1",
                },
            )
            self.assertTrue((Path(agent_dir) / "settings.json").exists())
            self.assertFalse((Path(home) / ".omp").exists())

    def test_default_install_does_not_create_archived_client_config(self):
        with tempfile.TemporaryDirectory() as home:
            subprocess.run(
                ["bash", str(INSTALL), "--claude", "--codex", "--omp"],
                capture_output=True, text=True, check=True, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
            )
            self.assertFalse((Path(home) / ".pi").exists())
            self.assertFalse((Path(home) / ".config" / "opencode").exists())

    def test_archived_client_flags_are_rejected(self):
        for flag in ("--pi", "--no-pi", "--opencode", "--no-opencode"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as home:
                result = subprocess.run(
                    ["bash", str(INSTALL), flag],
                    capture_output=True, text=True, check=False, env={"HOME": home, "PATH": _path(), "ADW_SKIP_PLUGIN": "1"},
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"unknown option: {flag}", result.stderr)


def _path() -> str:
    import os
    return os.environ.get("PATH", "/usr/bin:/bin")


if __name__ == "__main__":
    unittest.main()
