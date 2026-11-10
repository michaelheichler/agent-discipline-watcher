"""Preserve foreign artifacts because uninstall may remove only verified ADW ownership."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from lib import embedding_lease, nuke_runtime


def steps(home) -> nuke_runtime.NukeSteps:
    return nuke_runtime.NukeSteps(account_home=lambda: home, environment=lambda: {"PATH": ""})


def registered_directory(tmp_path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    directory = tmp_path.resolve() / "project/embedding-leases"
    directory.mkdir(parents=True)
    embedding_lease.register_root(home / ".adw/embedding-server", directory)
    return home, directory


def test_external_lease_cleanup_preserves_foreign_files_and_policy(tmp_path) -> None:
    home, directory = registered_directory(tmp_path)
    embedding_lease.acquire("owned", 1000.0, directory, 123)
    foreign_json = directory / "foreign.lease.json"
    foreign_json.write_text("{}", encoding="utf-8")
    foreign = directory / "notes.txt"
    foreign.write_text("Keep the note.", encoding="utf-8")
    policy = directory.parent / ".agent-discipline.json"
    policy.write_text('{"tests":"deny"}', encoding="utf-8")

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 0
    assert sorted(path.name for path in directory.iterdir()) == ["foreign.lease.json", "notes.txt"]
    assert foreign_json.read_text(encoding="utf-8") == "{}"
    assert foreign.read_text(encoding="utf-8") == "Keep the note."
    assert json.loads(policy.read_text(encoding="utf-8")) == {"tests": "deny"}


def test_empty_registered_lease_directories_disappear_after_uninstall(tmp_path) -> None:
    home, directory = registered_directory(tmp_path)

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 0
    assert not directory.exists()
    assert directory.parent.exists()


@pytest.mark.parametrize("unsafe", ["wrong-hash", "symlink"])
def test_untrusted_lease_root_registrations_prevent_any_uninstall(tmp_path, unsafe) -> None:
    home, directory = registered_directory(tmp_path)
    registry = home / ".adw/embedding-server/lease-roots"
    [record] = list(registry.glob("*.root"))
    break_registration(record, directory, unsafe)
    before = record.read_bytes()

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 2
    assert directory.exists()
    assert (home / ".adw").exists()
    assert record.read_bytes() == before


def break_registration(record, directory, unsafe) -> None:
    if unsafe == "wrong-hash":
        record.write_text(str(directory.parent / "other/embedding-leases"), encoding="utf-8")
        return
    destination = directory.parent / "foreign-directory"
    directory.rename(destination)
    directory.symlink_to(destination, target_is_directory=True)


@pytest.mark.parametrize("dry_run", [True, False])
def test_omp_installer_backups_appear_in_preview_and_removal(tmp_path, capsys, dry_run) -> None:
    home = tmp_path / "home"
    backup = home / ".omp/agent/settings.json.agent-discipline-watcher.bak.20261109000000"
    backup.parent.mkdir(parents=True)
    backup.write_text("{}", encoding="utf-8")
    option = {True: "--dry-run", False: "--yes"}[dry_run]

    result = nuke_runtime.main([option], steps=steps(home))

    assert result == 0
    assert str(backup) in capsys.readouterr().out
    assert backup.exists() is dry_run


def test_a_foreign_symlink_at_an_omp_backup_name_prevents_uninstall(tmp_path) -> None:
    home = tmp_path / "home"
    backup = home / ".omp/agent/settings.json.agent-discipline-watcher.bak.20261109000000"
    backup.parent.mkdir(parents=True)
    foreign = tmp_path / "foreign.lease.json"
    foreign.write_text("Keep this file.", encoding="utf-8")
    backup.symlink_to(foreign)

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 2
    assert backup.is_symlink()
    assert foreign.read_text(encoding="utf-8") == "Keep this file."


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS account plugin discovery")
def test_account_plugin_discovery_selects_only_verified_adw_manifests(tmp_path) -> None:
    home = tmp_path / "home"
    root = home / "Library/Application Support/Claude/local-agent-mode-sessions/a/b/rpm"
    adw = account_copy(root, "owned", {"name": "agent-discipline-watcher"})
    account_copy(root, "foreign", {"name": "other-plugin"})
    malformed = account_copy(root, "malformed", {})
    (malformed / ".claude-plugin/plugin.json").write_text("{", encoding="utf-8")

    plan = nuke_runtime.build_plan(home, steps(home))

    assert plan.removals == [adw]


def account_copy(root, name, manifest) -> Path:
    directory = root / name
    path = directory / ".claude-plugin/plugin.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return directory


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS account manifest safety")
def test_a_symlinked_selected_account_manifest_prevents_uninstall(tmp_path) -> None:
    home = tmp_path / "home"
    root = home / "Library/Application Support/Claude/local-agent-mode-sessions/a/b/rpm"
    adw = account_copy(root, "owned", {"name": "agent-discipline-watcher"})
    manifest = adw / ".claude-plugin/plugin.json"
    outside = tmp_path / "outside.json"
    manifest.rename(outside)
    manifest.symlink_to(outside)

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 2
    assert manifest.is_symlink()
    assert outside.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux account discovery boundary")
def test_linux_does_not_discover_macos_account_plugin_paths(tmp_path) -> None:
    home = tmp_path / "home"
    root = home / "Library/Application Support/Claude/local-agent-mode-sessions/a/b/rpm"
    adw = account_copy(root, "owned", {"name": "agent-discipline-watcher"})

    plan = nuke_runtime.build_plan(home, steps(home))

    assert plan.removals == []
    assert adw.exists()
