import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MERGE = ROOT / "pi" / "merge-settings.py"
INSTALL = ROOT / "pi" / "install.sh"
SKILL_DIR = "/opt/adw-checkout"  # noqa: S108 (placeholder path, never created)


def run_merge(*args: str) -> None:
    subprocess.run([sys.executable, str(MERGE), *args], check=True)


def load_merger():
    spec = importlib.util.spec_from_file_location("agent_discipline_omp_merge", MERGE)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MergeOmpSettingsTests(unittest.TestCase):
    def test_merge_adds_extension_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            run_merge("--settings", str(settings), "--skill-dir", SKILL_DIR)
            merged = json.loads(settings.read_text())
        target = f"{SKILL_DIR}/pi/extensions/agent-discipline-watcher/index.ts"
        self.assertEqual(merged["extensions"], [target])

    def test_double_merge_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            run_merge("--settings", str(settings), "--skill-dir", SKILL_DIR)
            once = settings.read_text()
            run_merge("--settings", str(settings), "--skill-dir", SKILL_DIR)
            twice = settings.read_text()
        self.assertEqual(once, twice)
        merged = json.loads(twice)
        self.assertEqual(len(merged["extensions"]), 1)

    def test_merge_strips_legacy_extensions(self):
        payload = {
            "extensions": [
                "/x/punctuation-discipline/extension/index.ts",
                "/x/unrelated/extension/index.ts",
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps(payload))
            run_merge("--settings", str(settings), "--skill-dir", SKILL_DIR)
            merged = json.loads(settings.read_text())
        text = json.dumps(merged)
        self.assertNotIn("punctuation-discipline", text)
        self.assertIn("unrelated/extension/index.ts", text)
        self.assertIn("agent-discipline-watcher/index.ts", text)

    def test_remove_drops_watcher_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            run_merge("--settings", str(settings), "--skill-dir", SKILL_DIR)
            run_merge("--settings", str(settings), "--skill-dir", SKILL_DIR, "--remove")
            merged = json.loads(settings.read_text())
        self.assertNotIn("extensions", merged)

    def test_merge_writes_through_a_settings_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real"
            real_dir.mkdir()
            real_settings = real_dir / "settings.json"
            real_settings.write_text(json.dumps({"model": "omp-default"}))
            link = Path(tmp) / "settings.json"
            link.symlink_to(real_settings)
            run_merge("--settings", str(link), "--skill-dir", SKILL_DIR)
            self.assertTrue(link.is_symlink())
            merged = json.loads(real_settings.read_text())
        self.assertEqual(merged["model"], "omp-default")
        self.assertEqual(len(merged["extensions"]), 1)

    def test_atomic_write_preserves_mode_and_secures_new_files(self):
        merger = load_merger()
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.json"
            existing.write_text("{}\n")
            existing.chmod(0o640)
            merger.atomic_write(existing, '{"extensions": []}\n')
            self.assertEqual(existing.stat().st_mode & 0o777, 0o640)

            created = Path(tmp) / "created.json"
            merger.atomic_write(created, '{"extensions": []}\n')
            self.assertEqual(created.stat().st_mode & 0o777, 0o600)


class InstallOmpScriptTests(unittest.TestCase):
    def test_claude_only_install_does_not_touch_omp_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            omp_agent = home / ".omp" / "agent"
            omp_agent.mkdir(parents=True)
            omp_settings = omp_agent / "settings.json"
            omp_settings.write_text('{"extensions": ["/keep/me.ts"]}\n')
            env = {
                **dict(__import__("os").environ),
                "HOME": str(home),
            }
            subprocess.run(
                [str(ROOT / "install.sh"), "--claude", "-y"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(omp_settings.read_text(), '{"extensions": ["/keep/me.ts"]}\n')

    def test_omp_install_links_extension_and_registers_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            omp_agent = home / ".omp" / "agent"
            omp_agent.mkdir(parents=True)
            env = {
                **dict(__import__("os").environ),
                "HOME": str(home),
            }
            subprocess.run(
                [str(INSTALL), "-y"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            link = omp_agent / "extensions" / "agent-discipline-watcher"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (ROOT / "pi/extensions/agent-discipline-watcher").resolve())
            merged = json.loads((omp_agent / "settings.json").read_text())
            self.assertEqual(len(merged["extensions"]), 1)

    def test_omp_remove_unlinks_extension_and_clears_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            omp_agent = home / ".omp" / "agent"
            omp_agent.mkdir(parents=True)
            env = {
                **dict(__import__("os").environ),
                "HOME": str(home),
            }
            subprocess.run([str(INSTALL), "-y"], cwd=ROOT, env=env, check=True)
            subprocess.run([str(INSTALL), "--remove", "-y"], cwd=ROOT, env=env, check=True)
            link = omp_agent / "extensions" / "agent-discipline-watcher"
            self.assertFalse(link.exists())
            merged = json.loads((omp_agent / "settings.json").read_text())
            self.assertNotIn("extensions", merged)

    def test_omp_remove_leaves_foreign_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            foreign = Path(tmp) / "foreign-extension"
            foreign.mkdir()
            omp_agent = home / ".omp" / "agent"
            extensions = omp_agent / "extensions"
            extensions.mkdir(parents=True)
            link = extensions / "agent-discipline-watcher"
            link.symlink_to(foreign)
            env = {
                **dict(__import__("os").environ),
                "HOME": str(home),
            }
            result = subprocess.run(
                [str(INSTALL), "--remove", "-y"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("warning:", result.stderr)
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), foreign.resolve())

    def test_omp_remove_leaves_real_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            omp_agent = home / ".omp" / "agent"
            target = omp_agent / "extensions" / "agent-discipline-watcher"
            target.mkdir(parents=True)
            marker = target / "keep-me.txt"
            marker.write_text("user data\n", encoding="utf-8")
            env = {
                **dict(__import__("os").environ),
                "HOME": str(home),
            }
            result = subprocess.run(
                [str(INSTALL), "--remove", "-y"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("warning:", result.stderr)
            self.assertTrue(target.is_dir())
            self.assertEqual(marker.read_text(encoding="utf-8"), "user data\n")


if __name__ == "__main__":
    unittest.main()
