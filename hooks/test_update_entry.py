from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "fixture" / "update.py"
    path.parent.mkdir()
    path.write_bytes(Path(__file__).with_name("update.py").read_bytes())
    library = path.parent / "lib"
    library.mkdir()
    (library / "__init__.py").write_text("", encoding="utf-8")
    (library / "update_runtime.py").write_text(
        "import argparse\n"
        "print('fixture runtime imported')\n"
        "def main(argv):\n"
        "    parser = argparse.ArgumentParser(prog='fixture updater')\n"
        "    parser.add_subparsers(required=True).add_parser('update')\n"
        "    parser.parse_args(argv)\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return path


def _invoke(path, flags, cwd):
    environment = {"PATH": os.defpath, "HOME": str(cwd), "PYTHONNOUSERSITE": "1"}
    return subprocess.run(
        [sys.executable, "-B", *flags, str(path), "update", "--help"],
        cwd=cwd, env=environment, capture_output=True, text=True, check=False, timeout=10,
    )


@pytest.mark.parametrize("flags", [[], ["-I"], ["-S"]])
@pytest.mark.parametrize("alias", ["absolute", "relative", "symlink"])
def test_entry_refuses_missing_isolation_flags_before_runtime_import(entry, tmp_path, flags, alias):
    path = entry
    if alias == "relative":
        path = entry.relative_to(tmp_path)
    elif alias == "symlink":
        path = tmp_path / "alias.py"
        path.symlink_to(entry)
    result = _invoke(path, flags, tmp_path)
    assert result.returncode == 2
    assert "requires Python -I -S" in result.stderr
    assert "fixture runtime imported" not in result.stdout


def test_entry_checks_flags_before_importing_path_modules(entry, tmp_path):
    (entry.parent / "pathlib.py").write_text("raise RuntimeError('untrusted path module imported')\n", encoding="utf-8")
    result = _invoke(entry, ["-S"], tmp_path)
    assert result.returncode == 2
    assert "requires Python -I -S" in result.stderr
    assert "untrusted path module" not in result.stderr


def test_isolated_entry_can_show_help_without_installing(entry, tmp_path):
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = _invoke(entry, ["-I", "-S"], tmp_path)
    assert result.returncode == 0
    assert "fixture runtime imported" in result.stdout
    assert "usage: fixture updater update" in result.stdout
    assert result.stderr == ""
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
