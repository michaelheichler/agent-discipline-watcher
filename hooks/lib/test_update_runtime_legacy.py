from __future__ import annotations

import json
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
    assert module.is_file()
    monkeypatch.setattr(update_runtime, "_account_home", lambda: home)
    monkeypatch.setattr(update_runtime, "__file__", str(module))
    release = SimpleNamespace(tag="v1.2.3", commit="a" * 40)
    monkeypatch.setattr(update_runtime.update_release, "latest_release", lambda: release)
    return home


def _legacy_checkout(root: Path, name: str = "agent-discipline-watcher") -> Path:
    manifest = root / ".claude-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": name}), encoding="utf-8")
    (root / "hooks").mkdir()
    (root / "hooks/run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    extension = root / "pi/extensions/agent-discipline-watcher"
    extension.mkdir(parents=True)
    (extension / "index.ts").write_text("export const legacy = true;\n", encoding="utf-8")
    return root


def test_preflight_accepts_protected_adw_checkout_links(managed_home):
    checkout = _legacy_checkout(managed_home / "Development/checkout")
    agent = managed_home / ".omp/agent"
    omp_link = agent / "extensions/agent-discipline-watcher"
    omp_link.parent.mkdir(parents=True)
    omp_link.symlink_to(checkout / "pi/extensions/agent-discipline-watcher")
    settings = agent / "settings.json"
    settings.write_text(
        json.dumps({"extensions": [str(checkout / "pi/extensions/agent-discipline-watcher/index.ts")]}),
        encoding="utf-8",
    )
    legacy = managed_home / ".agents/skills/agent-discipline-watcher"
    legacy.parent.mkdir(parents=True)
    legacy.symlink_to(checkout)

    update_runtime._preflight_paths(update_runtime._selected_paths(managed_home, ("omp",)), managed_home)

    assert omp_link.resolve() == checkout / "pi/extensions/agent-discipline-watcher"


def test_preflight_rejects_a_foreign_package_link(managed_home):
    checkout = _legacy_checkout(managed_home / "Development/checkout", name="different-package")
    link = managed_home / ".omp/agent/extensions/agent-discipline-watcher"
    link.parent.mkdir(parents=True)
    link.symlink_to(checkout / "pi/extensions/agent-discipline-watcher")

    with pytest.raises(RuntimeError, match="symlink"):
        update_runtime._preflight_paths(update_runtime._selected_paths(managed_home, ("omp",)), managed_home)


def test_preflight_rejects_a_missing_omp_registration(managed_home):
    checkout = _legacy_checkout(managed_home / "Development/checkout")
    agent = managed_home / ".omp/agent"
    link = agent / "extensions/agent-discipline-watcher"
    link.parent.mkdir(parents=True)
    link.symlink_to(checkout / "pi/extensions/agent-discipline-watcher")
    (agent / "settings.json").write_text(json.dumps({"extensions": []}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="symlink"):
        update_runtime._preflight_paths(update_runtime._selected_paths(managed_home, ("omp",)), managed_home)


def test_preflight_rejects_an_unprotected_legacy_root(managed_home):
    checkout = _legacy_checkout(managed_home / "Development/checkout")
    checkout.chmod(0o777)
    agent = managed_home / ".omp/agent"
    link = agent / "extensions/agent-discipline-watcher"
    link.parent.mkdir(parents=True)
    link.symlink_to(checkout / "pi/extensions/agent-discipline-watcher")
    (agent / "settings.json").write_text(
        json.dumps({"extensions": [str(checkout / "pi/extensions/agent-discipline-watcher/index.ts")]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="symlink"):
        update_runtime._preflight_paths(update_runtime._selected_paths(managed_home, ("omp",)), managed_home)


def test_preflight_rejects_legacy_links_to_different_roots(managed_home):
    first = _legacy_checkout(managed_home / "Development/first")
    second = _legacy_checkout(managed_home / "Development/second")
    agent = managed_home / ".omp/agent"
    omp_link = agent / "extensions/agent-discipline-watcher"
    omp_link.parent.mkdir(parents=True)
    omp_link.symlink_to(first / "pi/extensions/agent-discipline-watcher")
    settings = agent / "settings.json"
    settings.write_text(
        json.dumps({"extensions": [
            str(first / "pi/extensions/agent-discipline-watcher/index.ts"),
            str(second / "pi/extensions/agent-discipline-watcher/index.ts"),
        ]}),
        encoding="utf-8",
    )
    legacy = managed_home / ".agents/skills/agent-discipline-watcher"
    legacy.parent.mkdir(parents=True)
    legacy.symlink_to(second)

    with pytest.raises(RuntimeError, match="different source roots"):
        update_runtime._preflight_paths(update_runtime._selected_paths(managed_home, ("omp",)), managed_home)


def test_preflight_rejects_a_symlink_inside_the_legacy_source(managed_home, tmp_path):
    checkout = _legacy_checkout(managed_home / "Development/checkout")
    outside = tmp_path / "outside.ts"
    outside.write_text("outside\n", encoding="utf-8")
    index = checkout / "pi/extensions/agent-discipline-watcher/index.ts"
    index.unlink()
    index.symlink_to(outside)
    link = managed_home / ".omp/agent/extensions/agent-discipline-watcher"
    link.parent.mkdir(parents=True)
    link.symlink_to(checkout / "pi/extensions/agent-discipline-watcher")

    with pytest.raises(RuntimeError, match="symlink"):
        update_runtime._preflight_paths(update_runtime._selected_paths(managed_home, ("omp",)), managed_home)


def test_update_passes_the_validated_legacy_root_to_the_installer(managed_home, monkeypatch):
    repository = Path(__file__).resolve().parents[2]
    checkout = managed_home / "Development/checkout"
    shutil.copytree(repository, checkout, ignore=shutil.ignore_patterns(*update_runtime.EXCLUDED_NAMES))
    agent = managed_home / ".omp/agent"
    link = agent / "extensions/agent-discipline-watcher"
    link.parent.mkdir(parents=True)
    link.symlink_to(checkout / "pi/extensions/agent-discipline-watcher")
    (agent / "settings.json").write_text(
        json.dumps({"extensions": [str(checkout / "pi/extensions/agent-discipline-watcher/index.ts")]}),
        encoding="utf-8",
    )
    captured = {}
    updates = managed_home / ".adw/updates"
    updates.mkdir(parents=True)
    release = SimpleNamespace(tag="v1.2.3", commit="a" * 40)

    monkeypatch.setattr(
        update_runtime.update_release,
        "stage_release",
        lambda _release, destination: shutil.copytree(repository, destination, ignore=shutil.ignore_patterns(*update_runtime.EXCLUDED_NAMES)),
    )
    original_installer = update_runtime._run_installer

    def run_installer(source, hosts, environment):
        captured.update(environment)
        original_installer(source, hosts, environment)

    monkeypatch.setattr(update_runtime, "_run_installer", run_installer)

    update_runtime._perform_update(managed_home, updates, ("omp",), release)

    assert captured["ADW_LEGACY_INSTALL_DIR"] == str(checkout)
    installed = managed_home / update_runtime.INSTALL_PATH
    assert (managed_home / ".omp/agent/extensions/agent-discipline-watcher").resolve() == installed / "pi/extensions/agent-discipline-watcher"
    assert not (managed_home / ".agents/skills/agent-discipline-watcher").exists()
