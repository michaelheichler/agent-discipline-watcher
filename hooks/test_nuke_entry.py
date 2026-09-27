from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


FIXTURE_RUNTIME = (
    "from dataclasses import dataclass\n"
    "@dataclass\n"
    "class NukeSteps:\n"
    "    claude_cache: object = None\n"
    "    without_managed: object = None\n"
    "    run_claude: object = None\n"
    "def run_claude(arguments, environment):\n"
    "    return 'absent'\n"
    "def main(argv, *, steps):\n"
    "    print('argv', argv)\n"
    "    print('cache', getattr(steps.claude_cache, '__name__', None))\n"
    "    print('filter', getattr(steps.without_managed, '__name__', None))\n"
    "    print('cli', steps.run_claude is run_claude)\n"
    "    return 0\n"
)


@pytest.fixture
def entry(tmp_path: Path) -> Path:
    path = tmp_path / "fixture" / "nuke.py"
    path.parent.mkdir()
    path.write_bytes(Path(__file__).with_name("nuke.py").read_bytes())
    library = path.parent / "lib"
    library.mkdir()
    (library / "__init__.py").write_text("", encoding="utf-8")
    (library / "nuke_runtime.py").write_text(FIXTURE_RUNTIME, encoding="utf-8")
    return path


def _add_claude_adapters(entry: Path) -> None:
    library = entry.parent / "lib"
    (library / "claude_cache.py").write_text("NAME = 'cache'\n", encoding="utf-8")
    (library / "claude_presets.py").write_text("def without_managed(settings):\n    return settings\n", encoding="utf-8")


def _invoke(path: Path, flags: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = {"PATH": os.defpath, "HOME": str(cwd), "PYTHONNOUSERSITE": "1"}
    return subprocess.run(
        [sys.executable, "-B", *flags, str(path), "--dry-run"],
        cwd=cwd, env=environment, capture_output=True, text=True, check=False, timeout=10,
    )


@pytest.mark.parametrize("flags", [[], ["-I"], ["-S"]])
def test_entry_refuses_missing_isolation_flags(entry, tmp_path, flags) -> None:
    result = _invoke(entry, flags, tmp_path)
    assert result.returncode == 2
    assert "requires Python -I -S" in result.stderr
    assert "argv" not in result.stdout


def test_entry_wires_the_claude_adapters_into_the_runtime(entry, tmp_path) -> None:
    _add_claude_adapters(entry)
    result = _invoke(entry, ["-I", "-S"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["argv ['--dry-run']", "cache lib.claude_cache", "filter without_managed", "cli True"]


@pytest.mark.parametrize("arguments", [["--force"], ["--dry-run", "--yes"], ["-y"]])
def test_wrapper_rejects_anything_but_one_known_flag(arguments, tmp_path) -> None:
    wrapper = Path(__file__).parents[1] / "bin" / "adw-nuke"
    result = subprocess.run([str(wrapper), *arguments], cwd=tmp_path, capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 2
    assert "adw-nuke" in result.stderr


def test_entry_runs_without_the_claude_adapters(entry, tmp_path) -> None:
    result = _invoke(entry, ["-I", "-S"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1:3] == ["cache None", "filter None"]
