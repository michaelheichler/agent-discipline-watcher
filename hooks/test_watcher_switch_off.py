"""Parsed settings, because the plugin name survives a false toggle and a text match cannot see a hooks kill switch."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pre_bash
from lib import protected

PLUGIN = "agent-discipline-watcher@agent-discipline-watcher"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADW_ALLOW_PROTECTED_EDIT", raising=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return tmp_path / "home"


def rules(path: str, home: Path, content: str) -> list[str]:
    return [row["rule"] for row in protected.path_findings(protected.ProtectedWrite(path, home, content))]


@pytest.mark.parametrize(("path", "settings"), [
    ("~/.claude/settings.json", {"enabledPlugins": {PLUGIN: False}}),
    ("~/.claude/settings.json", {"disableAllHooks": True}),
    ("~/.claude/settings.json", {"env": {"ADW_ALLOW_PROTECTED_EDIT": "1"}}),
    (".claude/settings.local.json", {"disableAllHooks": True}),
    (".claude/settings.json", {"env": {"ADW_ALLOW_PROTECTED_EDIT": "1"}}),
])
def test_a_settings_write_that_switches_the_watcher_off_is_blocked(home: Path, path: str, settings: dict) -> None:
    assert rules(path, home, json.dumps(settings)) == ["watcher_wiring_removal"]


@pytest.mark.parametrize(("path", "content"), [
    ("~/.claude/settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}, "disableAllHooks": False})),
    ("~/.claude/settings.json", json.dumps({"env": {"FOO": "1"}})),
    (".other/settings.json", json.dumps({"disableAllHooks": True})),
    ("~/.claude/settings.json", '{"disableAllHooks": tru'),
])
def test_a_settings_write_that_keeps_the_watcher_on_passes(home: Path, path: str, content: str) -> None:
    assert rules(path, home, content) == []


def test_a_shell_redirect_that_disables_all_hooks_is_blocked(home: Path) -> None:
    command = "echo '{\"disableAllHooks\": true}' > .claude/settings.local.json"
    assert [row["rule"] for row in pre_bash.target_findings(command, {}, home)] == ["watcher_wiring_removal"]


def test_a_shell_redirect_with_an_unrelated_setting_passes(home: Path) -> None:
    command = "echo '{\"model\": \"x\"}' > .claude/settings.json"
    assert pre_bash.target_findings(command, {}, home) == []
