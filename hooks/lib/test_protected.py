"""Kept separate from scanner tests because these assert path policy, not source-content rules."""
from __future__ import annotations

import json
import os

import pytest

from lib import protected

SURFACE = ".claude/skills/agent-discipline-watcher/SKILL.md"
GRANT = json.dumps({protected.AUTH_KEY: True})
ATTACK = {
    "punctuation": False,
    "english": False,
    "clean_code": False,
    "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
    "state_root": "/tmp/attacker-state",
    "ledger_root": "/tmp/attacker-ledger",
}


def rules(path, home, config=None, content=None):
    return [finding["rule"] for finding in protected.path_findings(path, config, home, content)]


@pytest.mark.parametrize("relative", [
    ".claude/skills/agent-discipline-watcher/SKILL.md",
    ".claude/plugins/cache/agent-discipline-watcher/hooks/pre_write.py",
    ".agents/skills/agent-discipline-watcher/SKILL.md",
    ".config/opencode/plugins/agent-discipline-watcher.ts",
    ".omp/agent/extensions/agent-discipline-watcher/index.ts",
    ".local/bin/agent-discipline",
    ".local/bin/adw-cli/agent-discipline-shim",
])
def test_watcher_install_surfaces_block(tmp_path, relative):
    assert rules(str(tmp_path / relative), tmp_path) == ["watcher_install_surface"]


@pytest.mark.parametrize("relative", [
    ".claude/agents/reviewer.md",
    ".claude/commands/ship.md",
    ".claude/CLAUDE.md",
    ".claude/skills/humanizer-de/SKILL.md",
    ".claude/plugins/cache/other/hooks/hooks.json",
    ".codex/skills/humanizer/SKILL.md",
    ".omp/agent/config.yml",
    ".zshrc",
])
def test_other_client_paths_are_left_to_host_permissions(tmp_path, relative):
    assert rules(str(tmp_path / relative), tmp_path) == []


def test_watcher_state_mutation_blocks(tmp_path):
    target = tmp_path / ".agent-discipline" / "state" / "s1" / "state.json"
    assert rules(str(target), tmp_path) == ["state_mutation"]


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


def test_symlink_into_the_install_blocks(tmp_path):
    home = tmp_path / "home"
    target = home / ".claude/skills/agent-discipline-watcher/SKILL.md"
    target.parent.mkdir(parents=True)
    target.touch()
    link = tmp_path / "outside-home"
    os.symlink(target, link)
    assert rules(str(link), home) == ["watcher_install_surface"]


def test_install_symlink_target_outside_a_client_home_stays_editable(tmp_path):
    home = tmp_path / "home"
    checkout = tmp_path / "dev" / "agent-discipline-watcher"
    (checkout / "hooks").mkdir(parents=True)
    (checkout / "hooks" / "pre_bash.py").touch()
    (home / ".agents" / "skills").mkdir(parents=True)
    os.symlink(checkout, home / ".agents" / "skills" / "agent-discipline-watcher")
    assert rules(str(checkout / "hooks" / "pre_bash.py"), home) == []


def test_nonexistent_install_target_blocks(tmp_path):
    target = tmp_path / ".claude/skills/agent-discipline-watcher/new.md"
    assert rules(str(target), tmp_path) == ["watcher_install_surface"]


def test_symlink_plus_dotdot_still_reaches_the_install_path(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / "tmp").mkdir()
    link = home / "tmp" / "link"
    os.symlink("../.claude", link)
    sneaky = str(link) + "/../.claude/skills/agent-discipline-watcher/SKILL.md"
    assert rules(sneaky, home) == ["watcher_install_surface"]


def test_unresolvable_tilde_user_is_treated_as_protected(tmp_path):
    sneaky = "~definitely-nonexistent-adw-test-user/.claude/settings.json"
    assert rules(sneaky, tmp_path) == ["watcher_install_surface"]


def test_unresolvable_tilde_user_releases_under_env_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv(protected.AUTH_ENV, "1")
    sneaky = "~definitely-nonexistent-adw-test-user/.claude/settings.json"
    assert rules(sneaky, tmp_path) == []


def test_symlinked_home_still_matches_the_install_path(tmp_path):
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    linked_home = tmp_path / "linked-home"
    os.symlink(real_home, linked_home, target_is_directory=True)
    target = linked_home / ".claude/skills/agent-discipline-watcher/SKILL.md"
    assert rules(str(target), linked_home) == ["watcher_install_surface"]


def test_tilde_token_resolves_against_the_given_home(tmp_path):
    assert rules("~/.claude/skills/agent-discipline-watcher/SKILL.md", tmp_path) == ["watcher_install_surface"]


def test_pending_placeholder_is_ignored(tmp_path):
    assert rules("<pending>", tmp_path) == []
    assert rules("", tmp_path) == []


def test_home_root_itself_is_not_a_surface(tmp_path):
    assert rules(str(tmp_path), tmp_path) == []


def test_client_home_root_is_left_to_host_permissions(tmp_path):
    assert rules(str(tmp_path / ".claude"), tmp_path) == []


def _wired(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("relative", [
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".pi/agent/settings.json",
    ".omp/agent/settings.json",
])
def test_a_write_that_drops_the_watcher_hooks_blocks(tmp_path, relative):
    target = _wired(tmp_path / relative, '{"command": "~/x/agent-discipline-watcher/hooks/run.sh PreToolUse"}')
    assert rules(str(target), tmp_path, None, '{"permissions": []}') == ["watcher_wiring_removal"]


def test_a_write_that_keeps_the_watcher_hooks_passes(tmp_path):
    target = _wired(tmp_path / ".claude/settings.json", '{"command": "x/agent-discipline-watcher/hooks/run.sh Stop"}')
    kept = '{"permissions": ["Bash"], "command": "x/agent-discipline-watcher/hooks/run.sh Stop"}'
    assert rules(str(target), tmp_path, None, kept) == []


def test_an_unwired_settings_file_is_not_protected(tmp_path):
    target = _wired(tmp_path / ".claude/settings.json", '{"permissions": []}')
    assert rules(str(target), tmp_path, None, '{"permissions": ["Bash"]}') == []


def test_an_unreadable_write_to_a_wired_file_blocks(tmp_path):
    target = _wired(tmp_path / ".claude/settings.json", '{"command": "x/agent-discipline-watcher/hooks/run.sh Stop"}')
    assert rules(str(target), tmp_path) == ["watcher_wiring_removal"]


def test_existing_gate_config_is_sealed(tmp_path):
    target = tmp_path / "project" / ".agent-discipline.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert rules(str(target), tmp_path) == ["config_seal"]


@pytest.mark.parametrize("settings", [
    {"kill_switches": {"punctuation": True, "english": True, "clean_code": True}},
    {"exempt_paths": ["**"]},
    {"exempt_families": {"**": ["punctuation", "english", "clean_code"]}},
])
def test_a_config_that_silences_every_family_is_an_escape(tmp_path, settings):
    target = _config(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert rules(str(target), tmp_path, None, json.dumps(settings)) == ["config_seal"]


@pytest.mark.parametrize("settings", [
    {"exempt_families": {"LICENSE": ["english"]}},
    {"exempt_paths": ["vendor/**"]},
    {"gates": {"english": "off"}},
    {"kill_switches": {"english": True}},
])
def test_a_narrow_gate_config_edit_is_the_humans_to_make(tmp_path, settings):
    target = _config(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert rules(str(target), tmp_path, None, json.dumps(settings)) == []


def test_an_unreadable_write_to_an_existing_gate_config_blocks(tmp_path):
    target = _config(tmp_path)
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
    assert rules(str(tmp_path / SURFACE), tmp_path) == []


def test_a_config_key_does_not_release_the_path_rules(tmp_path):
    config = {protected.AUTH_KEY: True}
    assert protected.authorized(config) is False
    assert rules(str(tmp_path / SURFACE), tmp_path, config) == ["watcher_install_surface"]
    sealed = tmp_path / "project" / protected.CONFIG_SEAL_BASENAME
    sealed.parent.mkdir(parents=True)
    sealed.write_text("{}", encoding="utf-8")
    assert rules(str(sealed), tmp_path, config) == ["config_seal"]


def test_unset_authorization_env_does_not_release(tmp_path, monkeypatch):
    monkeypatch.setenv(protected.AUTH_ENV, "0")
    assert rules(str(tmp_path / SURFACE), tmp_path) == ["watcher_install_surface"]


def test_findings_carry_the_scanner_shape(tmp_path):
    finding = protected.path_findings(str(tmp_path / SURFACE), None, tmp_path)[0]
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
    {"rule_gates": {"suppression_escape_hatch": "enforce"}},
    {protected.AUTH_KEY: False},
])
def test_a_config_that_releases_nothing_protected_still_creates(tmp_path, payload):
    assert rules(str(_config(tmp_path)), tmp_path, None, json.dumps(payload)) == []


def test_a_config_cannot_release_a_strict_comment_rule(tmp_path):
    payload = {"rule_gates": {"what_comment": "off"}}
    assert rules(str(_config(tmp_path)), tmp_path, None, json.dumps(payload)) == ["config_seal"]


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", '{"gates": ["off"]}'])
def test_unreadable_config_text_grants_nothing(text):
    assert protected.grants_escape(text) is False


@pytest.mark.parametrize("payload", [
    ATTACK,
    {"punctuation": False, "english": False, "clean_code": False},
    {"gates": {"punctuation": "off", "english": "off", "clean_code": "off"}},
    {"punctuation": False, "gates": {"english": "off", "clean_code": "off"}},
])
def test_all_family_disables_and_root_redirection_grant_an_escape(payload):
    assert protected.grants_escape(json.dumps(payload)) is True


def test_one_family_disable_does_not_grant_an_escape():
    assert protected.grants_escape(json.dumps({"clean_code": False})) is False


def test_payload_without_roots_or_family_kill_does_not_grant_an_escape():
    assert protected.grants_escape(json.dumps({"max_rows": 4})) is False


def test_first_creation_of_an_attack_config_blocks(tmp_path):
    target = _config(tmp_path)
    assert not target.exists()
    assert rules(str(target), tmp_path, None, json.dumps(ATTACK)) == ["config_seal"]


def test_first_creation_of_a_benign_config_stays_allowed(tmp_path):
    target = _config(tmp_path)
    assert not target.exists()
    assert rules(str(target), tmp_path, None, json.dumps({"clean_code": False})) == []


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


def test_the_install_block_names_the_environment_escape(tmp_path):
    target = tmp_path / ".claude/skills/agent-discipline-watcher/SKILL.md"
    finding = protected.path_findings(str(target), None, tmp_path)[0]
    assert protected.AUTH_ENV in finding["action"]
    assert "every self-protection rule" in finding["action"]


def test_the_human_env_escape_still_releases_the_grant_block(tmp_path, monkeypatch):
    monkeypatch.setenv(protected.AUTH_ENV, "1")
    assert rules(str(_config(tmp_path)), tmp_path, None, GRANT) == []


def test_a_non_dict_config_argument_does_not_raise(tmp_path):
    assert protected.authorized(["authorized"]) is False
    target = tmp_path / ".claude/skills/agent-discipline-watcher/SKILL.md"
    assert rules(str(target), tmp_path, ["x"]) == ["watcher_install_surface"]


def test_is_install_surface_path_matches_the_finding_rule(tmp_path):
    assert protected.is_install_surface_path(str(tmp_path / ".local/bin/agent-discipline"), tmp_path)
    assert not protected.is_install_surface_path(str(tmp_path / ".claude/skills/humanizer/SKILL.md"), tmp_path)
