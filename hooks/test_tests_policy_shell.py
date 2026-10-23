"""One case per verb, because each shell route names its targets differently."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import protected, tests_policy
from test_tests_policy_gate import blocked_by, project, shell
from testing import make_repo, run_git as git

TEST_CHANGING_COMMANDS = [
    "mv /tmp/x.py tests",
    "cp /tmp/test_a.py src/",
    "cp a.py tests/",
    "install a.py tests/a.py",
    "rsync -a /tmp/x/ tests/",
    "mv tests/x.py /tmp/",
    "git checkout -- tests/x.py",
    "git restore tests/x.py",
    "git rm tests/x.py",
    "cd tests && git checkout -- x.py",
    "git apply /tmp/p.diff",
    "patch -p1 < /tmp/p.diff",
    "git stash pop",
    "tar -xzf a.tgz",
    "unzip a.zip",
    "sh -c 'git apply /tmp/p.diff'",
    "unzip a.zip -d tests",
    "unzip a.zip -d src",
    "tar -xzf a.tgz -C src",
    "git -C tests restore -- x.py",
    "git --work-tree=tests restore x.py",
    "git --work-tree tests restore x.py",
    "git -C a -C tests restore x.py",
    "git restore .",
    "git checkout .",
    "git checkout -- .",
    "git restore src/",
    "git restore 'src/*.py'",
    "git restore :/",
    "git rm -q config/esphome/bedside/fonts/*.txt",
    "git rm --cached tests/test_fonts.py",
    "git rm --cached tests/*.py",
]
TEST_SAFE_COMMANDS = [
    "git apply --check p.diff",
    "git checkout main",
    "git stash list",
    "unzip -l a.zip",
    "tar -czf a.tgz src",
    "tar -tzf a.tgz",
    "cp src/a.py src/b.py",
    "git restore src/a.py",
    "git -C src restore a.py",
]
FONTS = "config/esphome/bedside/fonts"
Names = tuple[str, ...]


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


@pytest.mark.parametrize("command", TEST_CHANGING_COMMANDS)
def test_deny_blocks_a_shell_command_that_changes_tests(tmp_path: Path, command: str) -> None:
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), tests_policy.RULE)


@pytest.mark.parametrize("opening", [
    ("allow", {}),
    ("deny", {"agent_type": tests_policy.TEST_WRITER}),
], ids=["allow", "test-writer"])
@pytest.mark.parametrize("command", TEST_CHANGING_COMMANDS)
def test_an_open_gate_lets_that_command_pass(tmp_path: Path, command: str, opening: tuple) -> None:
    policy, extra = opening
    assert not blocked_by(shell(project(tmp_path, tests=policy), command, **extra), tests_policy.RULE)


@pytest.mark.parametrize("command", TEST_SAFE_COMMANDS)
def test_deny_passes_a_shell_command_that_leaves_tests_alone(tmp_path: Path, command: str) -> None:
    assert not blocked_by(shell(project(tmp_path, tests="deny"), command), tests_policy.RULE)


def tracked_project(tmp_path: Path, tracked: Names, gone: Names = ()) -> Path:
    repo = project(make_repo(tmp_path), tests="deny")
    for name in tracked:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n", encoding="utf-8")
    git(repo, "add", "--", *tracked)
    for name in gone:
        (repo / name).unlink()
    return repo


@pytest.mark.parametrize("arrangement", [
    pytest.param(((f"{FONTS}/a.txt", f"{FONTS}/b.txt", "tests/test_fonts.py"), f"git rm -q --cached {FONTS}/*.txt"),
                 id="fonts"),
    pytest.param((("tests/test_fonts.py",), f"git rm -q --cached {FONTS}/*.txt"), id="no-match"),
    pytest.param((("tests/test_fonts.py",), 'git -C . rm --cached "config/*.txt"'), id="A9-git-c-no-match"),
])
def test_deny_passes_an_index_removal_whose_glob_names_no_test(tmp_path: Path, arrangement: tuple) -> None:
    tracked, command = arrangement
    assert not blocked_by(shell(tracked_project(tmp_path, tracked), command), tests_policy.RULE)


@pytest.mark.parametrize("arrangement", [
    pytest.param((("tests/test_fonts.py", f"{FONTS}/a.txt"), (), "git rm --cached tests/*.py"), id="worktree"),
    pytest.param((("tests/test_fonts.py",), ("tests/test_fonts.py",), "git rm --cached tests/*.py"), id="index-only"),
    pytest.param(((f"{FONTS}/a.txt", f"{FONTS}/test_glyphs.py"), (), f"git rm --cached {FONTS}/*"), id="mixed"),
    pytest.param((("tests/test_fonts.py",), (), 'git -C . rm --cached "tests/*.py"'), id="git-c"),
])
def test_deny_blocks_an_index_removal_whose_glob_names_a_test(tmp_path: Path, arrangement: tuple) -> None:
    tracked, gone, command = arrangement
    assert blocked_by(shell(tracked_project(tmp_path, tracked, gone), command), tests_policy.RULE)


@pytest.mark.parametrize("verb", ["cp", "install"])
def test_a_copy_onto_the_session_config_is_sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str) -> None:
    session = tmp_path / "session"
    elsewhere = tmp_path / "elsewhere"
    session.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert blocked_by(shell(project(session, tests="allow"), f"{verb} x .agent-discipline.json"), "config_seal")
