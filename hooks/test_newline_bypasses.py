"""Because the shell runs each line as its own command, a gate must judge a later line as if it came first."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import protected, tests_policy
from test_tests_policy_gate import blocked_by, project, shell


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


@pytest.mark.parametrize("route", [
    ("true\ncp /tmp/x.py tests/test_new.py", tests_policy.RULE),
    ("true\ngit rm --cached tests/test_a.py", tests_policy.RULE),
    ("true\ncp /tmp/x.json .agent-discipline.json", "config_seal"),
    ("true\nrm -rf ~/.adw/state", "state_deletion"),
    ("cp /tmp/x.py \\\n  tests/test_new.py", tests_policy.RULE),
], ids=["copy-onto-test", "index-removal", "copy-onto-config", "state-deletion", "continued-copy"])
def test_a_protected_command_blocks_wherever_a_newline_falls(tmp_path: Path, route: tuple) -> None:
    command, rule = route
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), rule)


@pytest.mark.parametrize("command", [
    "cd docs\ncat old.md",
    "ls -la \\\n  docs",
    "cat <<'EOF'\ncp /tmp/x.py tests/test_x.py\nEOF",
    'echo "first line\ncp /tmp/x.py tests/test_x.py"',
], ids=["two-reads", "continuation", "heredoc-body", "quoted-newline"])
def test_a_line_that_runs_no_protected_change_passes(tmp_path: Path, command: str) -> None:
    cwd = project(tmp_path, tests="deny")
    (cwd / "docs").mkdir()
    (cwd / "docs" / "old.md").write_text("old\n", encoding="utf-8")
    assert shell(cwd, command).get("decision") != "block"
