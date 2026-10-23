"""Because a recursive delete or move reaches every file below its operand, the gate must judge the files the folder holds."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import find_matches, protected, tests_policy
from test_protected_write_routes import tool_answer
from test_tests_policy_gate import blocked_by, project

ORDINARY = ("build/a.o", "build/notes.txt", "notes.md")


@pytest.fixture(autouse=True)
def _isolated_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)
    (tmp_path / "home" / ".adw").mkdir(parents=True)
    (tmp_path / "home" / ".adw" / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def folder_project(tmp_path: Path, policy: str = "deny", extra: tuple = ()) -> Path:
    cwd = tmp_path / "project"
    for name in (*ORDINARY, *extra):
        (cwd / name).parent.mkdir(parents=True, exist_ok=True)
        (cwd / name).write_text("x\n", encoding="utf-8")
    return project(cwd, tests=policy)


def crowded_folder(cwd: Path, count: int, suffix: str) -> None:
    folder = cwd / "crowd"
    folder.mkdir()
    for index in range(count):
        (folder / f"f{index}{suffix}").touch()


@pytest.mark.parametrize("command", [
    pytest.param("rm -r hooks", id="r"),
    pytest.param("rm -rf hooks", id="rf"),
    pytest.param("rm -R hooks", id="R"),
    pytest.param("rm --recursive hooks", id="recursive"),
    pytest.param("mv hooks old-hooks", id="mv"),
])
def test_a_recursive_change_to_a_folder_holding_a_test_is_denied(tmp_path: Path, command: str) -> None:
    cwd = folder_project(tmp_path, extra=("hooks/test_gate.py",))
    assert blocked_by(tool_answer(cwd, command), tests_policy.RULE)


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("arrangement", [
    pytest.param((("vendor/.agent-discipline.json",), "rm -rf vendor"), id="config"),
    pytest.param((("cache/.adw/state.json",), "rm -rf cache"), id="project-state"),
    pytest.param(((), 'rm -rf "$HOME"'), id="home-state"),
    pytest.param((("vendor/.agent-discipline.json",), "mv vendor old-vendor"), id="move-config"),
    pytest.param((("cache/.adw/state.json",), "mv cache old-cache"), id="move-project-state"),
    pytest.param(((), 'mv "$HOME" moved-home'), id="move-home-state"),
])
def test_a_recursive_change_reaching_watcher_files_is_denied(tmp_path: Path, arrangement: tuple, policy: str) -> None:
    extra, command = arrangement
    assert tool_answer(folder_project(tmp_path, policy, extra), command).get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param("rm -r build", id="delete-ordinary-folder"),
    pytest.param("mv build old-build", id="move-ordinary-folder"),
    pytest.param("ls -R hooks", id="list-test-folder"),
    pytest.param("cat hooks/test_gate.py > notes-copy.txt", id="read-a-test-into-notes"),
    pytest.param("cp vendor/.agent-discipline.json config-copy.json", id="copy-from-a-config"),
])
def test_an_ordinary_folder_change_or_a_read_of_a_protected_one_passes(tmp_path: Path, command: str) -> None:
    cwd = folder_project(tmp_path, extra=("hooks/test_gate.py", "vendor/.agent-discipline.json"))
    assert tool_answer(cwd, command).get("decision") != "block"


def test_a_recursive_delete_of_a_folder_too_large_to_walk_is_denied(tmp_path: Path) -> None:
    cwd = folder_project(tmp_path)
    crowded_folder(cwd, find_matches.MAX_ENTRIES + 1, ".o")
    assert blocked_by(tool_answer(cwd, "rm -r crowd"), "dynamic_write_target")


def test_a_deleting_find_at_the_match_limit_passes(tmp_path: Path) -> None:
    cwd = folder_project(tmp_path)
    crowded_folder(cwd, find_matches.MAX_MATCHES, ".tmp")
    assert tool_answer(cwd, "find crowd -name '*.tmp' -delete").get("decision") != "block"


def test_a_deleting_find_past_the_match_limit_is_denied(tmp_path: Path) -> None:
    cwd = folder_project(tmp_path)
    crowded_folder(cwd, find_matches.MAX_MATCHES + 1, ".tmp")
    assert blocked_by(tool_answer(cwd, "find crowd -name '*.tmp' -delete"), "dynamic_write_target")
