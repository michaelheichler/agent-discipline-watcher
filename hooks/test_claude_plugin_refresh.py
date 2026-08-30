from __future__ import annotations

import subprocess
from pathlib import Path

from lib import claude_cache, vendor


REPO_ROOT = vendor.REPO_ROOT
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
STUB = """#!/bin/sh
echo "$@" >> "$CLAUDE_STUB_LOG"
[ "${CLAUDE_STUB_FAIL:-0}" = "1" ] && exit 1
exit 0
"""


def _stub_claude(directory: Path, log: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / "claude"
    launcher.write_text(STUB, encoding="utf-8")
    launcher.chmod(0o755)
    log.touch()


def _install(home: Path, stub_dir: Path, log: Path, failing: bool = False) -> subprocess.CompletedProcess[str]:
    _stub_claude(stub_dir, log)
    return subprocess.run(
        [str(REPO_ROOT / "install.sh"), "--claude"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        env={
            "HOME": str(home),
            "PATH": f"{stub_dir}:{BASE_PATH}",
            "ADW_INSTALL_DIR": str(home / ".adw" / "install" / "adw"),
            "CLAUDE_STUB_LOG": str(log),
            "CLAUDE_STUB_FAIL": "1" if failing else "0",
        },
    )


def _seed_stale_cache(home: Path) -> Path:
    cache = (home / ".claude").joinpath(*claude_cache.CACHE_PARTS) / "deadbeef1234"
    cache.mkdir(parents=True)
    (cache / "marker").write_text("stale", encoding="utf-8")
    return cache


def test_the_installer_clears_the_stale_cache_then_reinstalls(tmp_path: Path) -> None:
    """Clear before installing because a stale checkout makes the plugin re-cache the old code."""
    home = tmp_path / "home"
    home.mkdir()
    stale = _seed_stale_cache(home)
    log = tmp_path / "calls.log"

    finished = _install(home, tmp_path / "stub", log)

    assert finished.returncode == 0, finished.stderr
    assert not stale.exists()
    assert "plugin install agent-discipline-watcher@agent-discipline-watcher" in log.read_text(encoding="utf-8")


def test_the_marketplace_refreshes_before_the_install(tmp_path: Path) -> None:
    """Refresh first because installing from a stale marketplace re-caches the code just cleared."""
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "calls.log"

    _install(home, tmp_path / "stub", log)
    calls = log.read_text(encoding="utf-8").splitlines()

    assert any("marketplace" in line for line in calls)
    assert calls.index(next(line for line in calls if "marketplace" in line)) < calls.index(
        next(line for line in calls if line.startswith("plugin install"))
    )


def test_the_state_directory_survives_the_installer(tmp_path: Path) -> None:
    """Spare the collector because it holds the settings the user configured, not cached code."""
    home = tmp_path / "home"
    home.mkdir()
    _seed_stale_cache(home)
    settings = home / ".adw" / "config.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"kept": true}', encoding="utf-8")

    _install(home, tmp_path / "stub", tmp_path / "calls.log")

    assert settings.read_text(encoding="utf-8") == '{"kept": true}'


def test_a_failing_plugin_command_prints_the_manual_commands(tmp_path: Path) -> None:
    """Fall back in writing because a silent failure leaves the user with no hooks and no message."""
    home = tmp_path / "home"
    home.mkdir()

    finished = _install(home, tmp_path / "stub", tmp_path / "calls.log", failing=True)

    assert finished.returncode == 0, finished.stderr
    assert "/plugin marketplace add" in finished.stdout
    assert "/plugin install agent-discipline-watcher@" in finished.stdout


def test_skipping_the_plugin_step_leaves_the_cache_alone(tmp_path: Path) -> None:
    """Honour the opt out because CI and the test suite must not reach the plugin system."""
    home = tmp_path / "home"
    home.mkdir()
    stale = _seed_stale_cache(home)
    log = tmp_path / "calls.log"
    stub_dir = tmp_path / "stub"
    _stub_claude(stub_dir, log)

    subprocess.run(
        [str(REPO_ROOT / "install.sh"), "--claude"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        env={
            "HOME": str(home),
            "PATH": f"{stub_dir}:{BASE_PATH}",
            "ADW_INSTALL_DIR": str(home / ".adw" / "install" / "adw"),
            "CLAUDE_STUB_LOG": str(log),
            "ADW_SKIP_PLUGIN": "1",
        },
    )

    assert stale.exists()
    assert log.read_text(encoding="utf-8") == ""
