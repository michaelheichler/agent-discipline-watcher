from __future__ import annotations

import fcntl
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import update_runtime


@pytest.fixture
def managed_home(tmp_path, monkeypatch):
    home = tmp_path / "account"
    installed = home / ".adw/install/agent-discipline-watcher"
    module = installed / "hooks/lib/update_runtime.py"
    module.parent.mkdir(parents=True)
    module.write_text("runtime = True\n", encoding="utf-8")
    (installed / ".adw-install-marker").write_text("agent-discipline-watcher\n", encoding="utf-8")
    monkeypatch.setattr(update_runtime, "_account_home", lambda: home)
    monkeypatch.setattr(update_runtime, "__file__", str(module))
    release = SimpleNamespace(tag="v1.2.3", commit="a" * 40)
    monkeypatch.setattr(update_runtime.update_release, "latest_release", lambda: release)
    return home


@pytest.mark.parametrize("arguments", [[], ["update"], ["update", "--dry-run"], ["update", "--code"], ["update", "--codex", "--source", "/tmp/repo"]])
def test_update_requires_explicit_hosts_and_rejects_source_override(arguments):
    with pytest.raises(SystemExit) as error:
        update_runtime.main(arguments)
    assert error.value.code == 2


def test_dry_run_reports_release_without_creating_update_state(managed_home, capsys):
    assert update_runtime.main(["update", "--omp", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "v1.2.3" in output
    assert "a" * 40 in output
    assert not (managed_home / ".adw/updates").exists()


def test_checkout_cannot_execute_live_update(managed_home, monkeypatch, capsys):
    monkeypatch.setattr(update_runtime, "__file__", str(managed_home / "checkout/update_runtime.py"))
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "installed" in capsys.readouterr().err
    assert not (managed_home / ".adw/updates").exists()


def test_account_home_comes_from_the_account_database(tmp_path, monkeypatch):
    expected = tmp_path / "account"
    monkeypatch.setenv("HOME", str(tmp_path / "injected"))
    monkeypatch.setattr(update_runtime.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(expected)))
    assert update_runtime._account_home() == expected


def test_installer_environment_cannot_inherit_write_or_code_overrides(managed_home, monkeypatch):
    for key in ("HOME", "PATH", "ADW_INSTALL_DIR", "ADW_PYTHON", "PYTHONPATH", "BASH_ENV", "GIT_CONFIG_COUNT"):
        monkeypatch.setenv(key, "/tmp/injected")
    environment = update_runtime._installer_environment(managed_home)
    assert environment["HOME"] == str(managed_home)
    assert environment["ADW_INSTALL_DIR"] == str(managed_home / ".adw/install/agent-discipline-watcher")
    assert environment["ADW_PYTHON"] == update_runtime.sys.executable
    assert not {"PYTHONPATH", "BASH_ENV", "GIT_CONFIG_COUNT", "ADW_SKIP_PLUGIN"}.intersection(environment)
    assert "/tmp/injected" not in environment.values()


def test_symlinked_updates_directory_is_refused(managed_home, tmp_path, capsys):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (managed_home / ".adw/updates").symlink_to(foreign, target_is_directory=True)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "symlink" in capsys.readouterr().err
    assert list(foreign.iterdir()) == []


def _fixture_release(source):
    files = {
        "install.sh": "#!/bin/sh\nexit 0\n",
        "bin/adw": "#!/bin/sh\nexit 0\n",
        "hooks/update.py": "updater = True\n",
        "hooks/lib/update_runtime.py": "runtime = 'new'\n",
        "pi/extensions/agent-discipline-watcher/index.ts": "export const active = true;\n",
        "hooks/codex-hooks.json": json.dumps({"hooks": {"PreToolUse": [{
            "matcher": "Bash", "hooks": [{"type": "command", "command": "ADW_CODEX_HOOK=1 __SKILL_DIR__/hooks/run.sh PreToolUse"}],
        }]}}),
    }
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (source / "bin/adw").chmod(0o755)
    return source


def _simulate_install(source, hosts, environment):
    installed = Path(environment["ADW_INSTALL_DIR"])
    shutil.rmtree(installed)
    shutil.copytree(source, installed)
    (installed / ".adw-install-marker").write_text("agent-discipline-watcher\n", encoding="utf-8")
    home = Path(environment["HOME"])
    command = home / ".adw/bin/adw"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.unlink(missing_ok=True)
    command.symlink_to(installed / "bin/adw")
    if "omp" in hosts:
        agent = home / ".omp/agent"
        link = agent / "extensions/agent-discipline-watcher"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to(installed / "pi/extensions/agent-discipline-watcher")
        settings = json.loads((agent / "settings.json").read_text()) if (agent / "settings.json").exists() else {}
        settings["extensions"] = [str(installed / "pi/extensions/agent-discipline-watcher/index.ts")]
        (agent / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    if "codex" in hosts:
        codex = home / ".codex"
        codex.mkdir(exist_ok=True)
        template = (source / "hooks/codex-hooks.json").read_text().replace("__SKILL_DIR__", str(installed))
        (codex / "hooks.json").write_text(template, encoding="utf-8")


@pytest.fixture
def available_update(managed_home, tmp_path, monkeypatch):
    source = _fixture_release(tmp_path / "published")
    monkeypatch.setattr(update_runtime.update_release, "stage_release", lambda release, destination: shutil.copytree(source, destination))
    monkeypatch.setattr(update_runtime, "_run_installer", _simulate_install)
    return SimpleNamespace(home=managed_home, source=source, installed=managed_home / update_runtime.INSTALL_PATH)


def test_update_verifies_files_and_wiring_before_recording_release(available_update):
    home = available_update.home
    for name in ("state", "ledger", "reports"):
        directory = home / ".adw" / name
        directory.mkdir()
        (directory / "keep.json").write_text('{"pending":true}', encoding="utf-8")
    settings = home / ".omp/agent/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme":"dark"}', encoding="utf-8")
    assert update_runtime.main(["update", "--omp", "--codex"]) == 0
    receipt = json.loads((home / ".adw/updates/installed.json").read_text())
    assert receipt["tag"] == "v1.2.3"
    assert receipt["commit"] == "a" * 40
    assert receipt["hosts"] == ["codex", "omp"]
    assert (available_update.installed / "hooks/lib/update_runtime.py").read_text() == "runtime = 'new'\n"
    assert json.loads(settings.read_text())["theme"] == "dark"
    for name in ("state", "ledger", "reports"):
        assert (home / ".adw" / name / "keep.json").read_text() == '{"pending":true}'


def test_download_failure_does_not_replace_install_or_wiring(available_update, monkeypatch):
    installed_module = available_update.installed / "hooks/lib/update_runtime.py"
    previous = installed_module.read_bytes()

    def failed_stage(release, destination):
        destination.mkdir()
        (destination / "partial").write_text("incomplete", encoding="utf-8")
        raise RuntimeError("download failed")

    monkeypatch.setattr(update_runtime.update_release, "stage_release", failed_stage)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert installed_module.read_bytes() == previous
    assert not (available_update.home / ".omp").exists()
    assert not (available_update.home / ".adw/updates/installed.json").exists()


def test_failed_install_restores_runtime_settings_and_managed_link(available_update, monkeypatch):
    installed_module = available_update.installed / "hooks/lib/update_runtime.py"
    previous = installed_module.read_bytes()
    agent = available_update.home / ".omp/agent"
    settings = agent / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"extensions":[],"theme":"dark"}\n', encoding="utf-8")
    original = settings.read_bytes()
    link = agent / "extensions/agent-discipline-watcher"
    link.parent.mkdir()
    link.symlink_to(available_update.installed / "pi/extensions/agent-discipline-watcher")

    def failed_install(source, hosts, environment):
        _simulate_install(source, hosts, environment)
        raise RuntimeError("installation failed")

    monkeypatch.setattr(update_runtime, "_run_installer", failed_install)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert installed_module.read_bytes() == previous
    assert settings.read_bytes() == original
    assert link.is_symlink()
    assert os.readlink(link) == str(available_update.installed / "pi/extensions/agent-discipline-watcher")
    assert not (available_update.home / ".adw/updates/installed.json").exists()


def test_missing_command_link_rolls_back_the_update(available_update, monkeypatch, capsys):
    previous = (available_update.installed / "hooks/lib/update_runtime.py").read_bytes()

    def missing_link(source, hosts, environment):
        _simulate_install(source, hosts, environment)
        (available_update.home / ".adw/bin/adw").unlink()

    monkeypatch.setattr(update_runtime, "_run_installer", missing_link)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "command" in capsys.readouterr().err
    assert (available_update.installed / "hooks/lib/update_runtime.py").read_bytes() == previous


def test_changed_installed_bytes_roll_back_the_update(available_update, monkeypatch, capsys):
    module = available_update.installed / "hooks/lib/update_runtime.py"
    previous = module.read_bytes()

    def altered_install(source, hosts, environment):
        _simulate_install(source, hosts, environment)
        module.write_text("runtime = False\n", encoding="utf-8")

    monkeypatch.setattr(update_runtime, "_run_installer", altered_install)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "verified release" in capsys.readouterr().err
    assert module.read_bytes() == previous
    assert not (available_update.home / ".adw/updates/installed.json").exists()


def test_foreign_settings_symlink_is_never_modified(available_update, tmp_path, capsys):
    foreign = tmp_path / "outside.json"
    foreign.write_text('{"private":true}', encoding="utf-8")
    settings = available_update.home / ".omp/agent/settings.json"
    settings.parent.mkdir(parents=True)
    settings.symlink_to(foreign)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "symlink" in capsys.readouterr().err
    assert settings.is_symlink()
    assert foreign.read_text() == '{"private":true}'


def test_symlinked_update_lock_is_refused(available_update, tmp_path, capsys):
    foreign = tmp_path / "foreign.lock"
    foreign.write_text("keep", encoding="utf-8")
    updates = available_update.home / ".adw/updates"
    updates.mkdir(mode=0o700)
    (updates / "update.lock").symlink_to(foreign)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "symlink" in capsys.readouterr().err
    assert foreign.read_text() == "keep"


def test_another_update_lock_prevents_a_second_update(available_update, capsys):
    updates = available_update.home / ".adw/updates"
    updates.mkdir(mode=0o700)
    descriptor = os.open(updates / "update.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert update_runtime.main(["update", "--omp"]) == 2
        assert "already running" in capsys.readouterr().err
    assert not (updates / "installed.json").exists()


def test_claude_plugin_is_verified_before_installer_receives_skip_flag(available_update, monkeypatch):
    catalog = available_update.home / ".adw/update-marketplace/.claude-plugin/marketplace.json"

    def pinned_plugin(home, source, commit, environment):
        assert source.name == "release"
        assert (source / "hooks/lib/update_runtime.py").read_bytes() == (available_update.source / "hooks/lib/update_runtime.py").read_bytes()
        assert commit == "a" * 40
        assert "ADW_SKIP_PLUGIN" not in environment
        catalog.parent.mkdir(parents=True)
        catalog.write_text(commit, encoding="utf-8")

    def after_plugin(source, hosts, environment):
        assert catalog.read_text() == "a" * 40
        assert environment["ADW_SKIP_PLUGIN"] == "1"
        _simulate_install(source, hosts, environment)

    monkeypatch.setattr(update_runtime, "_install_claude", pinned_plugin)
    monkeypatch.setattr(update_runtime, "_run_installer", after_plugin)
    assert update_runtime.main(["update", "--claude"]) == 0
    assert json.loads((available_update.home / ".adw/updates/installed.json").read_text())["hosts"] == ["claude"]


def test_installer_failure_restores_a_successfully_pinned_claude_catalog(available_update, monkeypatch):
    catalog = available_update.home / ".adw/update-marketplace/.claude-plugin/marketplace.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("previous", encoding="utf-8")

    def pinned_plugin(home, source, commit, environment):
        catalog.write_text(commit, encoding="utf-8")

    def failed_install(source, hosts, environment):
        raise RuntimeError("installer failure")

    monkeypatch.setattr(update_runtime, "_install_claude", pinned_plugin)
    monkeypatch.setattr(update_runtime, "_run_installer", failed_install)
    assert update_runtime.main(["update", "--claude"]) == 2
    assert catalog.read_text() == "previous"


@pytest.mark.parametrize("host", ["codex", "omp"])
def test_missing_host_routing_restores_previous_runtime(available_update, monkeypatch, capsys, host):
    module = available_update.installed / "hooks/lib/update_runtime.py"
    previous = module.read_bytes()

    def incomplete_install(source, hosts, environment):
        _simulate_install(source, hosts, environment)
        if host == "omp":
            (available_update.home / ".omp/agent/settings.json").write_text('{"extensions":[]}', encoding="utf-8")
        else:
            (available_update.home / ".codex/hooks.json").write_text('{"hooks":{}}', encoding="utf-8")

    monkeypatch.setattr(update_runtime, "_run_installer", incomplete_install)
    assert update_runtime.main(["update", f"--{host}"]) == 2
    assert host.lower() in capsys.readouterr().err.lower()
    assert module.read_bytes() == previous


def test_nonexecutable_released_command_does_not_replace_runtime(available_update, capsys):
    (available_update.source / "bin/adw").chmod(0o644)
    previous = (available_update.installed / "hooks/lib/update_runtime.py").read_bytes()
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "executable" in capsys.readouterr().err
    assert (available_update.installed / "hooks/lib/update_runtime.py").read_bytes() == previous


def test_release_without_updater_cannot_remove_the_update_path(available_update, capsys):
    (available_update.source / "hooks/update.py").unlink()
    previous = (available_update.installed / "hooks/lib/update_runtime.py").read_bytes()
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "supported updater" in capsys.readouterr().err
    assert (available_update.installed / "hooks/lib/update_runtime.py").read_bytes() == previous


def test_settings_link_into_runtime_is_not_a_managed_extension_link(available_update, capsys):
    settings = available_update.home / ".omp/agent/settings.json"
    settings.parent.mkdir(parents=True)
    module = available_update.installed / "hooks/lib/update_runtime.py"
    previous = module.read_bytes()
    settings.symlink_to(module)
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "symlink" in capsys.readouterr().err
    assert module.read_bytes() == previous


def test_an_invalid_install_marker_refuses_before_download(managed_home, capsys):
    marker = managed_home / update_runtime.INSTALL_PATH / ".adw-install-marker"
    marker.write_text("foreign", encoding="utf-8")
    assert update_runtime.main(["update", "--omp"]) == 2
    assert "ownership marker" in capsys.readouterr().err
    assert not (managed_home / ".adw/updates").exists()


def test_plugin_failure_never_runs_the_host_installer(available_update, monkeypatch):
    module = available_update.installed / "hooks/lib/update_runtime.py"
    previous = module.read_bytes()

    def failed_plugin(home, source, commit, environment):
        raise RuntimeError("unverified plugin")

    def forbidden_installer(source, hosts, environment):
        module.write_text("installer ran", encoding="utf-8")
        pytest.fail("unverified plugin reached the installer")

    monkeypatch.setattr(update_runtime, "_install_claude", failed_plugin)
    monkeypatch.setattr(update_runtime, "_run_installer", forbidden_installer)
    assert update_runtime.main(["update", "--claude"]) == 2
    assert module.read_bytes() == previous


def test_real_omp_installer_updates_only_the_temporary_home(managed_home, monkeypatch):
    repository = Path(__file__).resolve().parents[2]

    def staged_checkout(release, destination):
        shutil.copytree(repository, destination, ignore=shutil.ignore_patterns(*update_runtime.EXCLUDED_NAMES))

    monkeypatch.setattr(update_runtime.update_release, "stage_release", staged_checkout)
    settings = managed_home / ".omp/agent/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme":"dark","extensions":["other-extension"]}', encoding="utf-8")
    evidence = managed_home / ".adw/ledger/keep.json"
    evidence.parent.mkdir()
    evidence.write_text('{"pending":true}', encoding="utf-8")
    assert update_runtime.main(["update", "--omp"]) == 0
    installed = managed_home / update_runtime.INSTALL_PATH
    command = managed_home / ".adw/bin/adw"
    assert command.is_symlink()
    assert command.resolve() == installed / "bin/adw"
    assert (installed / "hooks/lib/update_runtime.py").read_bytes() == (repository / "hooks/lib/update_runtime.py").read_bytes()
    actual = json.loads(settings.read_text())
    assert actual["theme"] == "dark"
    assert "other-extension" in actual["extensions"]
    assert evidence.read_text() == '{"pending":true}'
    assert not (managed_home / ".claude").exists()
    assert not (managed_home / ".codex").exists()
