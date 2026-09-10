from pathlib import Path
from types import SimpleNamespace

import pytest

import pre_bash
from lib import update_policy


@pytest.fixture
def updater(tmp_path: Path) -> Path:
    root = tmp_path / ".adw/install/agent-discipline-watcher"
    (root / "bin").mkdir(parents=True)
    (root / "hooks/lib").mkdir(parents=True)
    (root / ".adw-install-marker").write_text("agent-discipline-watcher\n", encoding="utf-8")
    script = root / "bin/adw"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    (root / "hooks/update.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (root / "hooks/lib/update_runtime.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    link = tmp_path / ".adw/bin/adw"
    link.parent.mkdir()
    link.symlink_to(script)
    return link


def rules(command: str, home: Path, cwd: Path | None = None) -> list[str]:
    return [finding["rule"] for finding in pre_bash.command_findings(command, home=home, cwd=cwd)]


def test_the_managed_updater_accepts_explicit_host_choices(updater: Path, tmp_path: Path) -> None:
    assert rules(f"{updater} update --claude --codex --omp", tmp_path) == []
    assert rules(f"{updater} update --omp --dry-run", tmp_path) == []
    assert rules(f"{updater} update --help", tmp_path) == []


@pytest.mark.parametrize("suffix", ["update", "update --source /tmp/repo", "update --omp --agent-dir /tmp/agent"])
def test_unbounded_update_arguments_remain_blocked(updater: Path, tmp_path: Path, suffix: str) -> None:
    assert rules(f"{updater} {suffix}", tmp_path) == ["install_without_sandbox_home"]


def test_a_matching_name_does_not_authorize_an_updater(tmp_path: Path) -> None:
    assert rules("/tmp/adw update --omp", tmp_path) == ["install_without_sandbox_home"]
    assert rules("adw update --omp", tmp_path) == ["install_without_sandbox_home"]


def test_an_update_cannot_release_a_sibling_installer_or_state_deletion(updater: Path, tmp_path: Path) -> None:
    assert rules(f"{updater} update --omp && ./install.sh -y", tmp_path) == ["install_without_sandbox_home"]
    assert rules(f"{updater} update --omp && rm -rf ~/.adw/state", tmp_path) == ["state_deletion"]


def test_environment_prefixes_do_not_authorize_an_update(updater: Path, tmp_path: Path) -> None:
    assert rules(f"HOME=/tmp/other {updater} update --omp", tmp_path) == ["install_without_sandbox_home"]
    assert rules(f"env ADW_INSTALL_DIR=/tmp/other {updater} update --omp", tmp_path) == ["install_without_sandbox_home"]


def test_foreign_link_targets_do_not_inherit_updater_trust(updater: Path, tmp_path: Path) -> None:
    updater.unlink()
    updater.symlink_to("/tmp/foreign-updater")
    assert rules(f"{updater} update --omp", tmp_path) == ["install_without_sandbox_home"]


@pytest.mark.parametrize("relative", [".adw", ".adw/install", ".adw/install/agent-discipline-watcher/bin/adw"])
def test_writable_install_paths_cannot_authorize_updates(updater: Path, tmp_path: Path, relative: str) -> None:
    (tmp_path / relative).chmod(0o777)
    assert rules(f"{updater} update --omp", tmp_path) == ["install_without_sandbox_home"]


def test_missing_ownership_marker_cannot_authorize_updates(updater: Path, tmp_path: Path) -> None:
    (tmp_path / ".adw/install/agent-discipline-watcher/.adw-install-marker").unlink()
    assert rules(f"{updater} update --omp", tmp_path) == ["install_without_sandbox_home"]


def test_direct_installed_path_is_allowed(updater: Path, tmp_path: Path) -> None:
    assert rules(f"{updater.resolve()} update --omp", tmp_path) == []


def test_shell_payload_update_with_environment_prefix_blocks_at_full_gate(tmp_path: Path) -> None:
    config = {
        "ledger_root": str(tmp_path / "ledger"),
        "state_root": str(tmp_path / "state"),
    }
    payload = {
        "session_id": "shell-update",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "sh -c 'PATH=/tmp adw update --omp'"},
    }

    result = pre_bash.run(payload, config)

    assert result.get("decision") == "block"
    assert "install_without_sandbox_home" in result.get("reason", "")


def test_direct_managed_runtime_update_is_blocked_without_the_launcher(updater: Path, tmp_path: Path) -> None:
    runtime = updater.resolve().parents[1] / "hooks/update.py"
    alias = runtime.with_name("alias.py")
    alias.symlink_to(runtime)

    commands = [
        f"python3 {runtime} update --omp",
        f"/usr/bin/python3 -I -S {runtime} update --omp",
        f"PATH=/tmp python3 {runtime} update --omp",
        f"env PATH=/tmp python3 {runtime} update --omp",
        f"python3 {alias} update --omp",
        f"python3 {runtime.parent / 'lib/../update.py'} update --omp",
        "python3 $HOME/.adw/install/agent-discipline-watcher/hooks/update.py update --omp",
    ]

    assert all(rules(command, tmp_path) == ["install_without_sandbox_home"] for command in commands)


def test_relative_managed_runtime_uses_the_execution_cwd(updater: Path, tmp_path: Path) -> None:
    install_root = updater.resolve().parents[1]

    assert rules("python3 hooks/update.py update --omp", tmp_path, cwd=install_root) == [
        "install_without_sandbox_home",
    ]
    assert rules("python3 project/update.py update --omp", tmp_path, cwd=install_root) == []


@pytest.mark.parametrize("command", [
    "cd ~/.adw/install/agent-discipline-watcher; python3 hooks/update.py update --omp",
    "sh -c 'cd ~/.adw/install/agent-discipline-watcher; env PATH=/tmp python3 hooks/update.py update --omp'",
    "cd ~/.adw/install/agent-discipline-watcher; sh -c 'env PATH=/tmp python3 hooks/update.py update --omp'",
])
def test_relative_managed_runtime_is_blocked_at_full_gate(
    updater: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setattr(update_policy.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    config = {
        "ledger_root": str(tmp_path / "ledger"),
        "state_root": str(tmp_path / "state"),
    }
    payload = {
        "session_id": "relative-runtime-update",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }

    result = pre_bash.run(payload, config)

    assert result.get("decision") == "block"
    assert "install_without_sandbox_home" in result.get("reason", "")


def test_unrelated_project_update_script_is_not_classified_as_the_managed_runtime(tmp_path: Path) -> None:
    command = f"python3 {tmp_path / 'project/update.py'} update --omp"

    assert rules(command, tmp_path) == []


def test_direct_managed_runtime_update_is_blocked_at_full_gate(
    updater: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = updater.resolve().parents[1] / "hooks/update.py"
    monkeypatch.setattr(update_policy.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    config = {
        "ledger_root": str(tmp_path / "ledger"),
        "state_root": str(tmp_path / "state"),
    }
    payload = {
        "session_id": "direct-runtime-update",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": f"python3 {runtime} update --omp"},
    }

    result = pre_bash.run(payload, config)

    assert result.get("decision") == "block"
    assert "install_without_sandbox_home" in result.get("reason", "")
