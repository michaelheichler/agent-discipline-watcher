"""Protected-path policy tests: live client surfaces, the gate-config seal, and the authorization escape."""
from __future__ import annotations

import json
import os

import pytest

import protected

GRANT = json.dumps({protected.AUTH_KEY: True})


def rules(path, home, config=None, content=None):
    return [finding["rule"] for finding in protected.path_findings(path, config, home, content)]


@pytest.mark.parametrize("relative", [
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/skills/agent-discipline-watcher/SKILL.md",
    ".claude/agents/reviewer.md",
    ".claude/CLAUDE.md",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".pi/agent/settings.json",
    ".agents/skills/agent-discipline-watcher/SKILL.md",
    ".config/opencode/plugins/agent-discipline-watcher.ts",
    ".local/bin/agent-discipline",
])
def test_live_client_surfaces_block(tmp_path, relative):
    assert rules(str(tmp_path / relative), tmp_path) == ["live_client_surface"]


@pytest.mark.parametrize("relative", [
    ".claude/jobs/abc/tmp/scratch.py",
    ".claude/projects/proj/memory/note.md",
    ".claude/todos/list.json",
    ".claude/shell-snapshots/snap.sh",
    ".local/bin/ruff",
    ".config/nvim/init.lua",
    "dev/skills/agent-discipline-watcher/hooks/run.sh",
])
def test_non_wiring_paths_pass(tmp_path, relative):
    assert rules(str(tmp_path / relative), tmp_path) == []


def test_watcher_plugin_cache_path_blocks(tmp_path):
    target = tmp_path / ".claude/plugins/cache/agent-discipline-watcher/hooks/pre_write.py"
    assert rules(str(target), tmp_path) == ["live_client_surface"]


def test_other_plugin_cache_path_blocks(tmp_path):
    target = tmp_path / ".claude/plugins/cache/other/hooks/hooks.json"
    assert rules(str(target), tmp_path) == ["live_client_surface"]


def test_symlink_to_live_client_path_blocks(tmp_path):
    home = tmp_path / "home"
    target = home / ".claude/skills/agent-discipline-watcher/SKILL.md"
    target.parent.mkdir(parents=True)
    target.touch()
    link = tmp_path / "outside-home"
    os.symlink(target, link)
    assert rules(str(link), home) == ["live_client_surface"]


def test_nonexistent_live_client_target_blocks(tmp_path):
    target = tmp_path / ".claude/skills/agent-discipline-watcher/new.md"
    assert rules(str(target), tmp_path) == ["live_client_surface"]


def test_symlinked_home_still_matches_live_client_path(tmp_path):
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    linked_home = tmp_path / "linked-home"
    os.symlink(real_home, linked_home, target_is_directory=True)
    target = linked_home / ".claude/skills/agent-discipline-watcher/SKILL.md"
    assert rules(str(target), linked_home) == ["live_client_surface"]


def test_tilde_token_resolves_against_the_given_home(tmp_path):
    assert rules("~/.claude/settings.json", tmp_path) == ["live_client_surface"]


def test_pending_placeholder_is_ignored(tmp_path):
    assert rules("<pending>", tmp_path) == []
    assert rules("", tmp_path) == []


def test_home_root_itself_is_not_a_surface(tmp_path):
    assert rules(str(tmp_path), tmp_path) == []


def test_existing_gate_config_is_sealed(tmp_path):
    target = tmp_path / "project" / ".agent-discipline.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert rules(str(target), tmp_path) == ["config_seal"]


def test_first_creation_of_the_gate_config_is_allowed(tmp_path):
    target = tmp_path / "project" / ".agent-discipline.json"
    assert rules(str(target), tmp_path) == []


def test_gate_config_seal_is_case_insensitive(tmp_path):
    target = tmp_path / "project" / ".AGENT-DISCIPLINE.JSON"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert rules(str(target), tmp_path) == ["config_seal"]


def test_stat_failure_fails_closed(tmp_path, monkeypatch):
    def boom(_self):
        raise PermissionError("EACCES")

    monkeypatch.setattr(protected.Path, "exists", boom)
    target = tmp_path / "project" / ".agent-discipline.json"
    assert rules(str(target), tmp_path) == ["config_seal"]


def test_env_authorization_releases_every_rule(tmp_path, monkeypatch):
    monkeypatch.setenv(protected.AUTH_ENV, "1")
    assert rules(str(tmp_path / ".claude/settings.json"), tmp_path) == []


def test_a_config_key_does_not_release_the_path_rules(tmp_path):
    config = {protected.AUTH_KEY: True}
    assert protected.authorized(config) is False
    assert rules(str(tmp_path / ".claude/settings.json"), tmp_path, config) == ["live_client_surface"]
    sealed = tmp_path / "project" / protected.CONFIG_SEAL_BASENAME
    sealed.parent.mkdir(parents=True)
    sealed.write_text("{}", encoding="utf-8")
    assert rules(str(sealed), tmp_path, config) == ["config_seal"]


def test_unset_authorization_env_does_not_release(tmp_path, monkeypatch):
    monkeypatch.setenv(protected.AUTH_ENV, "0")
    assert rules(str(tmp_path / ".claude/settings.json"), tmp_path) == ["live_client_surface"]


def test_findings_carry_the_scanner_shape(tmp_path):
    finding = protected.path_findings(str(tmp_path / ".claude/settings.json"), None, tmp_path)[0]
    assert set(finding) == {"family", "rule", "line", "detail", "force", "snippet", "action"}
    assert finding["force"] is True
    assert finding["family"] == "self_protection"


def _config(tmp_path):
    return tmp_path / "project" / protected.CONFIG_SEAL_BASENAME


@pytest.mark.parametrize("payload", [
    {protected.AUTH_KEY: True},
    {"checks": {protected.AUTH_KEY: True}},
    {"rule_gates": {"suppression_escape_hatch": "off"}},
    {"rule_gates": {"config_seal": "observe"}},
    {"rule_gates": {"cap_override": "off"}},
    {"checks": {"rule_gates": {"state_deletion": "off"}}},
])
def test_a_config_that_releases_a_self_protection_rule_blocks_on_creation(tmp_path, payload):
    assert rules(str(_config(tmp_path)), tmp_path, None, json.dumps(payload)) == ["config_seal"]


@pytest.mark.parametrize("payload", [
    {},
    {"clean_code": False},
    {"rule_gates": {"what_comment": "off"}},
    {"rule_gates": {"suppression_escape_hatch": "enforce"}},
    {protected.AUTH_KEY: False},
])
def test_a_config_that_releases_nothing_protected_still_creates(tmp_path, payload):
    assert rules(str(_config(tmp_path)), tmp_path, None, json.dumps(payload)) == []


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", '{"gates": ["off"]}'])
def test_unreadable_config_text_grants_nothing(text):
    assert protected.grants_escape(text) is False


def test_a_self_granted_config_cannot_authorize_its_own_grant(tmp_path):
    granted = {protected.AUTH_KEY: True}
    assert rules(str(_config(tmp_path)), tmp_path, granted, GRANT) == ["config_seal"]


def test_the_grant_block_survives_an_existing_authorizing_config(tmp_path):
    target = _config(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text(GRANT, encoding="utf-8")
    assert rules(str(target), tmp_path, {protected.AUTH_KEY: True}, GRANT) == ["config_seal"]


def test_the_grant_block_names_the_environment_escape(tmp_path):
    finding = protected.path_findings(str(_config(tmp_path)), None, tmp_path, GRANT)[0]
    assert protected.AUTH_ENV in finding["action"]


def test_the_human_env_escape_still_releases_the_grant_block(tmp_path, monkeypatch):
    monkeypatch.setenv(protected.AUTH_ENV, "1")
    assert rules(str(_config(tmp_path)), tmp_path, None, GRANT) == []


def test_a_non_dict_config_argument_does_not_raise(tmp_path):
    assert protected.authorized(["authorized"]) is False
    assert rules(str(tmp_path / ".claude/settings.json"), tmp_path, ["x"]) == ["live_client_surface"]


def test_is_live_client_path_matches_the_finding_rule(tmp_path):
    assert protected.is_live_client_path(str(tmp_path / ".codex/config.toml"), tmp_path)
    assert not protected.is_live_client_path(str(tmp_path / ".claude/jobs/x"), tmp_path)
