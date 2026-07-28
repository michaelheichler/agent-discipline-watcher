"""Bash policy tests: bypass routes block, reads and sandboxed work pass."""
from __future__ import annotations

import pytest

import pre_bash


def rules(command, home=None, config=None):
    return sorted(f["rule"] for f in pre_bash.command_findings(command, config, home))


@pytest.mark.parametrize("command", [
    "./install.sh -y",
    "bash install.sh",
    "sh ./install.sh --no-codex",
    "python3 hooks/merge-claude-settings.py --settings x --skill-dir y",
    "python3 hooks/merge-codex-config.py --config x --skill-dir y",
    "python3 hooks/merge-pi-settings.py --settings x --skill-dir y",
])
def test_installers_without_sandbox_home_block(command):
    assert rules(command) == ["install_without_sandbox_home"]


@pytest.mark.parametrize("command", [
    'HOME="$(mktemp -d)" ./install.sh -y',
    "HOME=/tmp/box python3 hooks/merge-claude-settings.py --help",
    "HOME = /tmp/box ./install.sh",
])
def test_sandboxed_installers_pass(command):
    assert rules(command) == []


@pytest.mark.parametrize("command", [
    'echo "install.sh"',
    'grep -n install.sh README.md',
    'python3 -c \'paths = ["hooks/merge-claude-settings.py", "install.sh"]\'',
    'git log --oneline -- install.sh',
    'cat <<EOF\nsee hooks/merge-pi-settings.py for details\nEOF',
    'sed -n 1,5p install.sh',
])
def test_naming_an_installer_without_running_it_passes(command):
    assert "install_without_sandbox_home" not in rules(command)


@pytest.mark.parametrize("command", [
    "./install.sh",
    "cd repo && ./install.sh -y",
    "make setup | ./install.sh",
    "(cd repo; ./install.sh)",
])
def test_installer_in_command_position_still_blocks(command):
    assert "install_without_sandbox_home" in rules(command)


@pytest.mark.parametrize("command", [
    "git commit --no-verify -m 'x'",
    "git commit -n -m 'x'",
    "git commit -m 'x' --no-verify",
    "cd repo && git commit -n",
])
def test_commit_gate_bypass_blocks(command):
    assert rules(command) == ["commit_gate_bypass"]


@pytest.mark.parametrize("command", [
    "git commit -m 'fix(x): y'",
    "git log -n 5 --oneline",
    "git tag -n",
    "git commit --amend --no-edit",
    "npm run build -n",
])
def test_ordinary_git_and_shell_work_passes(command):
    assert rules(command) == []


@pytest.mark.parametrize("command", [
    "CLEANCODER_FUNC_BLOCK_LINES=500 python3 -m pytest -q",
    "CLEANCODER_FILE_BLOCK_LINES=9000 pytest",
    "ADW_MAX_SCAN_BYTES=1 pytest",
    "ADW_ALLOW_PROTECTED_EDIT=1 python3 hooks/pre_write.py",
])
def test_cap_and_escape_overrides_block(command):
    assert rules(command) == ["cap_override"]


@pytest.mark.parametrize("command", [
    "rm -rf ~/.agent-discipline",
    "rm -f .agent-discipline.json",
    "rm -rf $HOME/.agent-discipline/state",
    "shred ~/.agent-discipline/ledger/ledger.jsonl",
])
def test_state_deletion_blocks(command):
    assert "state_deletion" in rules(command)


def test_shell_write_to_live_surface_blocks(tmp_path):
    command = "echo '{}' > " + str(tmp_path / ".claude/settings.json")
    assert rules(command, tmp_path) == ["live_client_surface"]


@pytest.mark.parametrize("template", [
    "echo x > {}",
    "echo x >> {}",
    "echo x 1> {}",
    "cat src | tee {}",
    "sed -i '' s/a/b/ {}",
    "cp /tmp/src {}",
    "mv /tmp/src {}",
    "ln -snf /tmp/src {}",
    "rm -f {}",
    "dd if=/tmp/src of={}",
    "chmod 600 {}",
])
def test_every_mutating_form_blocks(tmp_path, template):
    target = str(tmp_path / ".codex/config.toml")
    assert "live_client_surface" in rules(template.format(target), tmp_path)


@pytest.mark.parametrize("template", [
    "cat {} 2>/dev/null",
    "python3 -m json.tool {} 2>&1",
    "grep -n run.sh {} 2>>/tmp/err.log",
    "git diff -- {}",
    "wc -l {}",
])
def test_reads_with_stderr_redirection_pass(tmp_path, template):
    target = str(tmp_path / ".claude/settings.json")
    assert rules(template.format(target), tmp_path) == []


def test_real_write_alongside_stderr_redirection_still_blocks(tmp_path):
    target = str(tmp_path / ".claude/settings.json")
    command = f"echo '{{}}' > {target} 2>/dev/null"
    assert rules(command, tmp_path) == ["live_client_surface"]


def test_quoted_and_variable_targets_are_resolved(tmp_path):
    assert rules('echo x > "$HOME/.codex/config.toml"', tmp_path) == ["live_client_surface"]
    assert rules("echo x > ${HOME}/.codex/config.toml", tmp_path) == ["live_client_surface"]
    assert rules("echo x > ~/.codex/config.toml", tmp_path) == ["live_client_surface"]


def test_repo_writes_are_untouched(tmp_path):
    assert rules("echo x > hooks/claude-settings.snippet.json", tmp_path) == []


def test_unbalanced_quotes_do_not_crash(tmp_path):
    assert isinstance(rules("echo 'unterminated > " + str(tmp_path / ".pi/agent/settings.json"), tmp_path), list)


def test_multiple_rules_report_together(tmp_path):
    command = "CLEANCODER_FUNC_BLOCK_LINES=500 git commit -n -m x"
    assert rules(command, tmp_path) == ["cap_override", "commit_gate_bypass"]


def test_authorization_releases_the_bash_policy(tmp_path):
    config = {"protected_paths_authorized": True}
    assert rules("./install.sh -y", tmp_path, config) == []


def test_empty_command_is_allowed():
    assert rules("") == []


def test_run_denies_and_allows_through_the_hook_contract(tmp_path):
    denied = pre_bash.run({"tool_input": {"command": "./install.sh -y"}})
    assert denied.get("decision") == "block"
    assert pre_bash.run({"tool_input": {"command": "ls -la"}}) == {}
