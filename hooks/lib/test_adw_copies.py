"""Built in a fake home, because the copies a user removes sit where each host installed them."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import adw_copies

ADW = "agent-discipline-watcher"
OWN_RELEASE = "0.30.0"
ACCOUNT_PLUGINS = "Library/Application Support/Claude/local-agent-mode-sessions/org-1/account-1/rpm"
CLI_CACHE = ".claude/plugins/cache/agent-discipline-watcher/agent-discipline-watcher"


def _changelog(root: Path, release: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n## {release} (2026-10-01)\n\n- A change.\n", encoding="utf-8")
    return root


def _manifest(root: Path, name: str = ADW) -> Path:
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return root


def _account_copy(home: Path, folder: str, release: str) -> Path:
    return _changelog(_manifest(home / ACCOUNT_PLUGINS / folder), release)


def _own(tmp_path: Path) -> Path:
    return _changelog(tmp_path / "running", OWN_RELEASE)


def _install_record(home: Path, install_path: Path) -> None:
    record = home / ".claude" / "plugins" / "installed_plugins.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    entries = {f"{ADW}@{ADW}": [{"installPath": str(install_path)}]}
    record.write_text(json.dumps({"version": 2, "plugins": entries}), encoding="utf-8")


def _roots(found: list[adw_copies.Copy]) -> list[Path]:
    return [copy.root for copy in found]


@pytest.mark.parametrize("release", [
    pytest.param("0.29.9", id="older-patch-line"),
    pytest.param("0.9.0", id="older-minor-that-sorts-later-as-text"),
])
def test_an_older_account_plugin_copy_is_stale(tmp_path: Path, release: str) -> None:
    home = tmp_path / "home"
    account = _account_copy(home, "plugin_old", release)

    found = adw_copies.stale(home, _own(tmp_path))

    assert _roots(found) == [account]


def test_the_notice_names_the_path_of_an_older_account_plugin_copy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    account = _account_copy(home, "plugin_old", "0.29.0")
    own = _own(tmp_path)

    text = adw_copies.notice(adw_copies.stale(home, own), own)

    assert str(account) in text


@pytest.mark.parametrize("release", [
    pytest.param(OWN_RELEASE, id="equal"),
    pytest.param("0.31.0", id="newer-minor"),
    pytest.param("0.100.0", id="newer-minor-that-sorts-earlier-as-text"),
    pytest.param("1.0.0", id="newer-major"),
])
def test_an_equal_or_newer_account_plugin_copy_is_not_stale(tmp_path: Path, release: str) -> None:
    home = tmp_path / "home"
    _account_copy(home, "plugin_new", release)

    assert adw_copies.stale(home, _own(tmp_path)) == []


def test_an_old_cache_folder_the_install_record_does_not_name_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    installed = _changelog(_manifest(home / CLI_CACHE / "installed"), "0.29.0")
    _changelog(_manifest(home / CLI_CACHE / "leftover"), "0.20.0")
    _install_record(home, installed)

    found = adw_copies.stale(home, _own(tmp_path))

    assert _roots(found) == [installed]


def test_an_account_plugin_folder_of_another_plugin_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    adw = _account_copy(home, "plugin_adw", "0.29.0")
    _changelog(_manifest(home / ACCOUNT_PLUGINS / "plugin_other", "another-plugin"), "0.1.0")

    found = adw_copies.stale(home, _own(tmp_path))

    assert _roots(found) == [adw]


def test_a_copy_without_a_changelog_is_not_listed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    listed = _account_copy(home, "plugin_with_changelog", "0.29.0")
    _manifest(home / ACCOUNT_PLUGINS / "plugin_without_changelog")

    found = adw_copies.copies(home)

    assert _roots(found) == [listed]
