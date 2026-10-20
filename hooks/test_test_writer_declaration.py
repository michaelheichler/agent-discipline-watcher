"""Guarded by declared name too, because hosts take the agent type from the name field and not from the file name."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
from lib import protected

DECLARED = "---\nname: adw-test-writer\n---\nWrites tests.\n"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADW_ALLOW_PROTECTED_EDIT", raising=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return tmp_path / "home"


def rules(path: str, home: Path, content: str | None) -> list[str]:
    return [row["rule"] for row in protected.path_findings(protected.ProtectedWrite(path, home, content))]


@pytest.mark.parametrize(("path", "content"), [
    (".claude/agents/helper.md", DECLARED),
    (".claude/agents/sub/adw-test-writer.md", "---\nname: x\n---\n"),
    (".codex/agents/helper.toml", 'name = "adw-test-writer"\n'),
    (".omp/agents/helper.md", DECLARED),
    ("~/.claude/agents/helper.md", "---\nname: 'adw-test-writer'\n---\n"),
])
def test_an_agent_file_that_becomes_the_test_writer_is_blocked(home: Path, path: str, content: str) -> None:
    assert rules(path, home, content) == ["test_writer_definition"]


@pytest.mark.parametrize("content", ["---\nname: other\n---\n", None])
def test_rewriting_an_agent_file_that_declares_the_test_writer_is_blocked(home: Path, content: str | None) -> None:
    helper = Path(".claude/agents/helper.md")
    helper.parent.mkdir(parents=True)
    helper.write_text(DECLARED, encoding="utf-8")
    assert rules(str(helper), home, content) == ["test_writer_definition"]


def test_a_shell_redirect_that_declares_the_test_writer_is_blocked(home: Path) -> None:
    command = "printf 'name: adw-test-writer\\n' > .claude/agents/helper.md"
    assert [row["rule"] for row in pre_bash.target_findings(command, {}, home)] == ["test_writer_definition"]


@pytest.mark.parametrize(("path", "content"), [
    (".claude/agents/reviewer.md", "---\nname: reviewer\n---\nHand tests to adw-test-writer.\n"),
    ("docs/helper.md", DECLARED),
])
def test_a_file_that_does_not_define_the_test_writer_agent_stays_editable(home: Path, path: str, content: str) -> None:
    assert rules(path, home, content) == []
