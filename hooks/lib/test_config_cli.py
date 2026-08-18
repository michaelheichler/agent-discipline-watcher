import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin" / "agent-discipline"


class ConfigCliTests(unittest.TestCase):
    def run_cli(self, *args, input_text=None, cwd=None, check=True):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=check,
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

    def test_status_reads_a_conflicting_top_level_key_like_the_gate(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / ".agent-discipline.json").write_text(
                json.dumps({"punctuation": False, "checks": {"english": True, "punctuation": True}})
            )

            result = self.run_cli("status", str(project))

            assert json.loads(result.stdout)["checks"] == {
                "punctuation": False,
                "english": True,
                "clean_code": True,
            }

    def test_configure_clears_a_conflicting_top_level_check_key(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / ".agent-discipline.json").write_text(json.dumps({"punctuation": False}))

            self.run_cli("configure", str(project), "--checks", "punctuation,english")

            config = json.loads((project / ".agent-discipline.json").read_text())
            assert "punctuation" not in config
            assert config["checks"] == {
                "punctuation": True,
                "english": True,
                "clean_code": False,
            }

    def test_configure_refuses_to_shadow_an_ancestor_config(self):
        assert CLI.exists()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            child = project / "src"
            child.mkdir(parents=True)
            (project / ".agent-discipline.json").write_text(json.dumps({"checks": {"english": False}}))

            result = self.run_cli("configure", str(child), "--checks", "punctuation", check=False)

            assert result.returncode != 0
            assert "shadow" in result.stderr
            assert not (child / ".agent-discipline.json").exists()

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

    def test_exempt_family_refuses_to_shadow_an_ancestor_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            child = project / "src"
            child.mkdir()
            (project / ".agent-discipline.json").write_text(json.dumps({"exempt_families": {}}))

            result = self.run_cli("exempt-family", "a.md", str(child), "--families", "english", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("shadow", result.stderr)
            self.assertFalse((child / ".agent-discipline.json").exists())

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


class ReportingCliTests(unittest.TestCase):
    def run_cli(self, *args, cli=None, check=True):
        return subprocess.run(
            [sys.executable, str(cli or CLI), *args],
            check=check, text=True, capture_output=True,
        )

    def _ledger(self, tmp, rows, adjudications=()):
        directory = Path(tmp) / "ledger"
        directory.mkdir()
        (directory / "ledger.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows)
        )
        if adjudications:
            (directory / "adjudications.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in adjudications)
            )
        return directory

    def _would_block(self, ts, turn_id, rule):
        return {"ts": ts, "turn_id": turn_id, "outcome": "would_block",
                "family": "clean_code", "rule": rule, "path": "a.py"}

    def test_observe_report_prints_would_block_rows_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = self._ledger(tmp, [
                self._would_block("2026-01-02T00:00:00+00:00", "t2", "long_comment"),
                self._would_block("2026-01-01T00:00:00+00:00", "t1", "what_comment"),
                {"ts": "2026-01-03T00:00:00+00:00", "turn_id": "t3", "outcome": "block",
                 "family": "clean_code", "rule": "hollow_test", "path": "b.py"},
                {"ts": "2026-01-04T00:00:00+00:00", "turn_id": "t4",
                 "outcome": "would_block", "family": "english",
                 "rule": "banned_dash", "path": "c.md"},
            ])
            result = self.run_cli("observe-report", "clean_code", tmp,
                                  "--root", str(directory))
            lines = result.stdout.splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("what_comment", lines[0])
            self.assertIn("turn=t1", lines[0])
            self.assertIn("long_comment", lines[1])
            self.assertNotIn("hollow_test", result.stdout)

    def test_observe_report_says_so_when_the_family_has_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = self._ledger(tmp, [
                self._would_block("2026-01-01T00:00:00+00:00", "t1", "what_comment"),
            ])
            result = self.run_cli("observe-report", "english", tmp,
                                  "--root", str(directory))
            self.assertIn("no would_block rows recorded", result.stdout)

    def test_a_missing_ledger_exits_non_zero_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("observe-report", "clean_code", tmp,
                                  "--root", str(Path(tmp) / "absent"), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no ledger at", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_false_signal_rate_reports_the_floor_instead_of_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = self._ledger(tmp, [
                self._would_block(f"2026-01-01T00:00:0{n}+00:00", f"t{n}", "what_comment")
                for n in range(5)
            ])
            result = self.run_cli("false-signal-rate", "clean_code", tmp,
                                  "--root", str(directory))
            self.assertIn("below the 20-turn floor", result.stdout)
            self.assertNotIn("None", result.stdout)

    def test_false_signal_rate_prints_the_rate_above_the_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = self._ledger(
                tmp,
                [self._would_block("2026-01-01T00:00:00+00:00", f"t{n}", "what_comment")
                 for n in range(40)],
                adjudications=[
                    {"family": "clean_code", "ref_ts": "x", "label": False},
                    {"family": "clean_code", "ref_ts": "y", "label": False},
                    {"family": "clean_code", "ref_ts": "z", "label": True},
                    {"family": "english", "ref_ts": "w", "label": False},
                ],
            )
            result = self.run_cli("false-signal-rate", "clean_code", tmp,
                                  "--root", str(directory))
            self.assertIn("= 1.00", result.stdout)

    def test_adjudicate_records_one_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = self._ledger(tmp, [
                self._would_block("2026-01-01T00:00:00+00:00", "t1", "what_comment"),
            ])
            self.run_cli("adjudicate", "clean_code", "2026-01-01T00:00:00+00:00", tmp,
                         "--root", str(directory), "--false-signal")
            written = [json.loads(line) for line in
                       (directory / "adjudications.jsonl").read_text().splitlines()]
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0]["family"], "clean_code")
            self.assertEqual(written[0]["ref_ts"], "2026-01-01T00:00:00+00:00")
            self.assertIs(written[0]["label"], False)

    def test_adjudicate_requires_a_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("adjudicate", "clean_code", "ts", tmp, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--justified", result.stderr)

    def test_a_symlinked_entry_point_still_resolves_its_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "agent-discipline"
            link.symlink_to(CLI)
            directory = self._ledger(tmp, [
                self._would_block("2026-01-01T00:00:00+00:00", "t1", "what_comment"),
            ])
            result = self.run_cli("observe-report", "clean_code", tmp,
                                  "--root", str(directory), cli=link)
            self.assertIn("what_comment", result.stdout)


if __name__ == "__main__":
    unittest.main()
