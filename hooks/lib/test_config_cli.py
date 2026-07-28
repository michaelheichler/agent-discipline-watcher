import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin" / "agent-discipline"


class ConfigCliTests(unittest.TestCase):
    def run_cli(self, *args, input_text=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=True,
            text=True,
            capture_output=True,
            input=input_text,
            cwd=cwd,
        )

    def test_configure_writes_selected_project_config(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            self.run_cli(
                "configure",
                str(project),
                "--checks",
                "punctuation,english",
            )

            config = json.loads((project / ".agent-discipline.json").read_text())
            assert config == {
                "checks": {
                    "punctuation": True,
                    "english": True,
                    "clean_code": False,
                }
            }

    def test_status_prints_effective_project_config(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / ".agent-discipline.json").write_text(
                json.dumps({"checks": {"english": False}})
            )

            result = self.run_cli("status", str(project))

            assert json.loads(result.stdout) == {
                "project": str(project.resolve()),
                "config_path": str((project / ".agent-discipline.json").resolve()),
                "checks": {
                    "punctuation": True,
                    "english": False,
                    "clean_code": True,
                },
                "exempt_families": {},
            }

    def test_status_finds_parent_project_config(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            child = project / "src"
            child.mkdir(parents=True)
            (project / ".agent-discipline.json").write_text(
                json.dumps({"checks": {"english": False}})
            )

            result = self.run_cli("status", str(child))

            assert json.loads(result.stdout)["checks"]["english"] is False

    def test_configure_defaults_to_current_project(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "configure",
                    "--checks",
                    "clean_code",
                ],
                check=True,
                text=True,
                capture_output=True,
                cwd=project,
            )

            config = json.loads((project / ".agent-discipline.json").read_text())
            assert config["checks"] == {
                "punctuation": False,
                "english": False,
                "clean_code": True,
            }

    def test_interactive_configure_accepts_numbers(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            result = self.run_cli("configure", str(project), input_text="1 3\n")

            config = json.loads((project / ".agent-discipline.json").read_text())
            assert config["checks"] == {
                "punctuation": True,
                "english": False,
                "clean_code": True,
            }
            assert "1" in result.stdout
            assert "punctuation" in result.stdout
            assert "clean_code" in result.stdout

    def test_interactive_configure_enter_keeps_effective_checks(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / ".agent-discipline.json").write_text(
                json.dumps({"checks": {"english": False}})
            )

            self.run_cli("configure", str(project), input_text="\n")

            config = json.loads((project / ".agent-discipline.json").read_text())
            assert config["checks"] == {
                "punctuation": True,
                "english": False,
                "clean_code": True,
            }

    def test_interactive_configure_accepts_none(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            self.run_cli("configure", str(project), input_text="none\n")

            config = json.loads((project / ".agent-discipline.json").read_text())
            assert config["checks"] == {
                "punctuation": False,
                "english": False,
                "clean_code": False,
            }

    def test_no_args_prints_status_and_configure_hint(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            result = self.run_cli(cwd=project)

            assert '"checks"' in result.stdout
            assert "configure" in result.stdout


class ExemptFamilyCliTests(unittest.TestCase):
    def run_cli(self, *args, check=True):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=check, text=True, capture_output=True,
        )

    def _project(self, tmp):
        project = Path(tmp) / "project"
        project.mkdir()
        return project

    def _config(self, project):
        return json.loads((project / ".agent-discipline.json").read_text())

    def test_it_writes_the_family_exemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            self.run_cli("exempt-family", "last_assistant_message.md", str(project),
                         "--families", "english")
            written = self._config(project)["exempt_families"]
            self.assertEqual(written, {"last_assistant_message.md": ["english"]})

    def test_clear_removes_one_pattern_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            self.run_cli("exempt-family", "a.md", str(project), "--families", "english")
            self.run_cli("exempt-family", "b.md", str(project), "--families", "punctuation")
            self.run_cli("exempt-family", "a.md", str(project), "--clear")
            self.assertEqual(self._config(project)["exempt_families"], {"b.md": ["punctuation"]})

    def test_an_unknown_family_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            result = self.run_cli("exempt-family", "a.md", str(project),
                                  "--families", "englsh", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown family", result.stderr)
            self.assertFalse((project / ".agent-discipline.json").exists())

    def test_configure_preserves_an_existing_exemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            self.run_cli("exempt-family", "a.md", str(project), "--families", "english")
            self.run_cli("configure", str(project), "--checks", "punctuation")
            config = self._config(project)
            self.assertEqual(config["exempt_families"], {"a.md": ["english"]})
            self.assertFalse(config["checks"]["english"])


if __name__ == "__main__":
    unittest.main()
