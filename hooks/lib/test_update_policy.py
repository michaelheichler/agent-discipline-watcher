from pathlib import Path

import pytest

import pre_bash


@pytest.fixture
def updater(tmp_path: Path) -> Path:
    root = tmp_path / ".adw/install/agent-discipline-watcher"
    (root / "bin").mkdir(parents=True)
    (root / ".adw-install-marker").write_text("agent-discipline-watcher\n", encoding="utf-8")
    script = root / "bin/adw"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    link = tmp_path / ".adw/bin/adw"
    link.parent.mkdir()
    link.symlink_to(script)
    return link


def rules(command: str, home: Path) -> list[str]:
    return [finding["rule"] for finding in pre_bash.command_findings(command, home=home)]


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
