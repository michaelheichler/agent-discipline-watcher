import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "hooks" / "run.sh"
VERSION_FILE = ROOT / ".python-version"
PYLINTRC = ROOT / ".pylintrc"
WORKFLOW = ROOT / ".github" / "workflows" / "pylint.yml"

FLOOR = VERSION_FILE.read_text(encoding="utf-8").strip()

DISPATCH = {
    "SessionStart": "session_start.py",
    "UserPromptSubmit": "prompt_submit.py",
    "PreToolUse": "pre_tool.py",
    "PreCommit": "pre_tool.py",
    "PostToolUse": "record.py",
    "PostToolBatch": "batch.py",
    "PostToolUseFailure": "failure.py",
    "SubagentStart": "subagent_start.py",
    "SubagentStop": "subagent_stop.py",
    "Stop": "stop.py",
    "SessionEnd": "session_end.py",
    "JudgeReview": "judge_review.py",
}

EXPECTED_USAGE = "usage: run.sh " + "|".join(DISPATCH)

# The stub answers only through PATH resolution, because an absolute interpreter would run the real hook and drop this marker.
STUB_MARKER = "adw-stub"


class RunDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._stub(Path(self.tmp.name), "python3", meets_floor=True)
        env = os.environ.copy()
        env["PATH"] = self.tmp.name + os.pathsep + env.get("PATH", "")
        env.pop("ADW_PYTHON", None)
        self.env = env

    def tearDown(self):
        self.tmp.cleanup()

    def _stub(self, directory, name, *, meets_floor, version="3.99.0"):
        # run.sh probes a candidate with -c before running a hook, so the stub answers that call separately.
        stub = Path(directory) / name
        stub.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "-c" ]\nthen\n  {"printf \"%s\\n\" \"" + version + "\"; " if meets_floor else ""}exit {0 if meets_floor else 1}\nfi\n'
            f'echo "{STUB_MARKER}:{name} $@"\n'
        )
        stub.chmod(0o755)
        return stub

    def _isolated_bin(self, name):
        path = Path(self.tmp.name) / name
        path.mkdir(parents=True, exist_ok=True)
        for tool in ("dirname", "sh"):
            source = Path("/usr/bin") / tool
            if not source.exists():
                source = Path("/bin") / tool
            link = path / tool
            if not link.exists():
                link.symlink_to(source)
        return path

    def _run(self, *args, env=None):
        return subprocess.run(
            [str(RUN_SH), *args],
            env=env or self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _run_isolated(self, bin_dir, *args, **overrides):
        env = os.environ.copy()
        env.pop("ADW_PYTHON", None)
        env["PATH"] = str(bin_dir)
        env.update(overrides)
        return self._run(*args, env=env)

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

    def test_missing_target_script_exits_2(self):
        isolated = Path(self.tmp.name) / "isolated"
        isolated.mkdir()
        run_copy = isolated / "run.sh"
        run_copy.write_text(RUN_SH.read_text(encoding="utf-8"), encoding="utf-8")
        run_copy.chmod(0o755)

        result = subprocess.run(
            [str(run_copy), "SessionStart"], env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(result.stdout.strip())

    def test_missing_interpreter_exits_2(self):
        result = self._run_isolated(self._isolated_bin("no-python"), "SessionStart")
        self.assertEqual(result.returncode, 2)
        self.assertIn(FLOOR, result.stderr)

    def test_interpreter_below_the_floor_is_refused(self):
        bin_dir = self._isolated_bin("stale-python")
        self._stub(bin_dir, "python3", meets_floor=False)

        result = self._run_isolated(bin_dir, "SessionStart")
        self.assertEqual(result.returncode, 2)
        self.assertIn(FLOOR, result.stderr)
        self.assertFalse(result.stdout.strip())

    def test_a_versioned_interpreter_outranks_a_stale_python3_beside_it(self):
        bin_dir = self._isolated_bin("mixed-python")
        self._stub(bin_dir, "python3", meets_floor=False)
        self._stub(bin_dir, "python3.99", meets_floor=True)

        result = self._run_isolated(bin_dir, "SessionStart")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(f"{STUB_MARKER}:python3.99"), result.stdout)

    def test_a_later_path_entry_supplies_the_interpreter_when_the_first_is_stale(self):
        stale = self._isolated_bin("first-stale")
        self._stub(stale, "python3", meets_floor=False)
        fresh = self._isolated_bin("second-fresh")
        self._stub(fresh, "python3", meets_floor=True)

        result = self._run_isolated(f"{stale}{os.pathsep}{fresh}", "SessionStart")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(f"{STUB_MARKER}:python3"), result.stdout)

    def test_newest_compatible_interpreter_wins_across_path_entries(self):
        older = self._isolated_bin("older-compatible")
        self._stub(older, "python3.9", meets_floor=True, version="3.9.9")
        newer = self._isolated_bin("newer-compatible")
        self._stub(newer, "python3.14", meets_floor=True, version="3.14.0")

        result = self._run_isolated(f"{older}{os.pathsep}{newer}", "SessionStart")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(f"{STUB_MARKER}:python3.14"), result.stdout)

    def test_adw_python_overrides_the_path_search(self):
        override_dir = Path(self.tmp.name) / "override"
        override_dir.mkdir()
        override = self._stub(override_dir, "chosen-python", meets_floor=True)

        result = self._run("SessionStart", env={**self.env, "ADW_PYTHON": str(override)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(f"{STUB_MARKER}:chosen-python"), result.stdout)

    def test_adw_python_below_the_floor_exits_2_without_falling_back(self):
        override_dir = Path(self.tmp.name) / "override-stale"
        override_dir.mkdir()
        override = self._stub(override_dir, "stale-python", meets_floor=False)

        result = self._run("SessionStart", env={**self.env, "ADW_PYTHON": str(override)})
        self.assertEqual(result.returncode, 2)
        self.assertIn(FLOOR, result.stderr)
        self.assertFalse(result.stdout.strip())

    def test_probe_agrees_with_the_running_interpreter(self):
        floor = tuple(int(part) for part in FLOOR.split("."))
        result = self._run("SessionStart", env={**self.env, "ADW_PYTHON": sys.executable})
        if sys.version_info[:len(floor)] >= floor:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertEqual(result.returncode, 2)

    def test_an_exported_cdpath_does_not_corrupt_path_resolution(self):
        result = subprocess.run(
            ["./run.sh", "SessionStart"],
            cwd=str(ROOT / "hooks"),
            env={**self.env, "CDPATH": f".{os.pathsep}{ROOT}"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(STUB_MARKER), result.stdout)


class PythonFloorTests(unittest.TestCase):
    def test_version_file_names_one_major_minor_floor(self):
        self.assertRegex(FLOOR, r"^\d+\.\d+$")

    def test_run_sh_takes_the_floor_from_the_version_file_and_pins_no_version(self):
        source = RUN_SH.read_text(encoding="utf-8")
        self.assertIn(".python-version", source)
        self.assertNotRegex(source, r"\bpython3\.\d", "run.sh must resolve the interpreter, not name a version")
        self.assertNotIn(FLOOR, source)

    def test_pylint_py_version_matches_the_version_file(self):
        declared = re.search(r"^py-version\s*=\s*(\S+)$", PYLINTRC.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(declared, "pylintrc declares no py-version")
        self.assertEqual(declared.group(1), FLOOR)

    def test_ci_reads_the_floor_from_the_version_file(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python-version-file: .python-version", workflow)
        self.assertNotRegex(workflow, r"python-version:\s*\S", "CI must not pin a version beside the version file")


if __name__ == "__main__":
    unittest.main()
