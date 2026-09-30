"""Run through the launcher, because users type the command."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lib import vendor

LAUNCHER = vendor.REPO_ROOT / "bin" / "adw-config"


def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LAUNCHER), *args], cwd=cwd, capture_output=True, text=True, check=False,
    )


def policy(cwd: Path) -> dict:
    return json.loads((cwd / ".agent-discipline.json").read_text(encoding="utf-8"))


def test_status_reports_the_allow_default_without_a_file(tmp_path: Path) -> None:
    result = cli(tmp_path, "status")
    assert result.returncode == 0
    assert "tests: allow" in result.stdout.splitlines()
    assert not (tmp_path / ".agent-discipline.json").exists()


def test_tests_deny_writes_the_policy_and_keeps_other_keys(tmp_path: Path) -> None:
    (tmp_path / ".agent-discipline.json").write_text('{"custom": 7, "max_rows": 3}', encoding="utf-8")
    result = cli(tmp_path, "tests", "deny")
    assert result.returncode == 0
    assert policy(tmp_path) == {"custom": 7, "max_rows": 3, "tests": "deny"}
    assert "tests: deny" in cli(tmp_path, "status").stdout.splitlines()


def test_family_off_turns_the_family_off_in_status(tmp_path: Path) -> None:
    assert cli(tmp_path, "family", "english", "off").returncode == 0
    assert policy(tmp_path) == {"gates": {"english": "off"}}
    lines = cli(tmp_path, "status").stdout.splitlines()
    assert "  english: off (off)" in lines
    assert "  punctuation: on (enforce)" in lines


def test_an_alias_family_switches_its_leaves(tmp_path: Path) -> None:
    cli(tmp_path, "family", "clean_code", "off")
    lines = cli(tmp_path, "status").stdout.splitlines()
    assert "  comment: off (off)" in lines
    assert "  code: off (off)" in lines
    cli(tmp_path, "family", "clean_code", "on")
    assert "  comment: on (enforce)" in cli(tmp_path, "status").stdout.splitlines()


@pytest.mark.parametrize(("args", "code"), [
    (("tests", "maybe"), 1),
    (("family", "nope", "off"), 2),
    (("family", "prose", "observe"), 2),
    (("purge",), 2),
])
def test_a_bad_request_exits_nonzero_and_writes_nothing(tmp_path: Path, args: tuple[str, ...], code: int) -> None:
    assert cli(tmp_path, *args).returncode == code
    assert not (tmp_path / ".agent-discipline.json").exists()


def test_a_misspelled_tests_value_fails_the_load(tmp_path: Path) -> None:
    (tmp_path / ".agent-discipline.json").write_text('{"tests": "Deny"}', encoding="utf-8")
    result = cli(tmp_path, "status")
    assert result.returncode == 1
    assert "could not be read safely" in result.stderr
