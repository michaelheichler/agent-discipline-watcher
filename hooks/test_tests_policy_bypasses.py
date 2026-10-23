"""Run in a real repo, because each route reached a test through a path the gate never resolved."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import protected, tests_policy
from test_tests_policy_gate import blocked_by, project, shell
from testing import make_repo, run_git as git

TRACKED = ("tests/test_x.py", "tests/x.py", "src/a.py", "docs/old.md", "x.py")
UNKNOWN_COPY = 'cp x.py "$D"'
NAMED_ROUTES = [
    pytest.param("git rm -r --cached {tests,src}", id="brace"),
    pytest.param("git rm -r --cached t\\ests", id="backslash"),
    pytest.param('git rm --cached "$T"', id="unset-variable"),
    pytest.param("T=tests; git rm -r --cached $T", id="set-variable"),
    pytest.param("true; cd tests; git rm x.py", id="mid-command-cd"),
    pytest.param("cd tests && sh -c 'git rm x.py'", id="shell-c-after-cd"),
    pytest.param("git mv tests/test_x.py y.py", id="git-mv"),
]


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def tracked_repo(tmp_path: Path, policy: str = "deny", extra: tuple = ()) -> Path:
    repo = project(make_repo(tmp_path), tests=policy)
    for name in (*TRACKED, *extra):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "--", *TRACKED, *extra)
    (repo / "notes").mkdir()
    return repo


@pytest.mark.parametrize("command", NAMED_ROUTES)
def test_deny_blocks_a_route_that_reaches_tests(tmp_path: Path, command: str) -> None:
    assert blocked_by(shell(tracked_repo(tmp_path), command), tests_policy.RULE)


@pytest.mark.parametrize("command", NAMED_ROUTES)
def test_an_open_gate_lets_that_route_pass(tmp_path: Path, command: str) -> None:
    assert not blocked_by(shell(tracked_repo(tmp_path, "allow"), command), tests_policy.RULE)


@pytest.mark.parametrize("policy", ["allow", "deny"])
def test_an_unknown_copy_destination_blocks_whatever_the_tests_policy(tmp_path: Path, policy: str) -> None:
    assert blocked_by(shell(tracked_repo(tmp_path, policy), UNKNOWN_COPY), "dynamic_write_target")


FOLDER_ROUTES = [
    pytest.param("git rm -r --cached src", id="rm"),
    pytest.param("git restore src", id="restore"),
    pytest.param("git checkout -- src", id="checkout"),
    pytest.param("git restore src/", id="restore-slash"),
]


@pytest.mark.parametrize("command", FOLDER_ROUTES)
def test_deny_blocks_a_folder_route_whose_index_holds_a_test(tmp_path: Path, command: str) -> None:
    cwd = tracked_repo(tmp_path, extra=("src/test_a.py",))
    assert blocked_by(shell(cwd, command), tests_policy.RULE)


@pytest.mark.parametrize("command", [
    "cd docs && git rm old.md",
    "cd tests && cat test_x.py",
    'D=notes; cp x.py "$D/"',
    *FOLDER_ROUTES,
])
def test_deny_passes_a_route_that_reaches_no_test(tmp_path: Path, command: str) -> None:
    assert shell(tracked_repo(tmp_path), command).get("decision") != "block"
