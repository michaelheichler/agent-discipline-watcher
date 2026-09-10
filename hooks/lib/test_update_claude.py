from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from lib import update_claude, update_claude_state


COMMIT = "0123456789abcdef0123456789abcdef01234567"
REPOSITORY = "michaelheichler/agent-discipline-watcher"


def _staged_release(root: Path) -> Path:
    for directory in ("commands", "hooks", "pi", "skills"):
        target = root / directory
        target.mkdir(parents=True)
        (target / f"{directory}.txt").write_text(directory, encoding="utf-8")
    manifest = root / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"name": update_claude.PLUGIN_NAME}), encoding="utf-8")
    return root


def _config(home: Path, relative: Path = Path(".claude")) -> Path:
    config = home / relative
    (config / "plugins").mkdir(parents=True)
    return config


def _installed(config: Path, cache: Path, commit: str, scope: str = "user") -> None:
    path = config / "plugins" / "installed_plugins.json"
    path.write_text(
        json.dumps({
            "version": 2,
            "plugins": {
                update_claude.PLUGIN_ID: [{
                    "scope": scope,
                    "installPath": str(cache),
                    "version": commit[:12],
                    "gitCommitSha": commit,
                }],
            },
        }),
        encoding="utf-8",
    )


def _copy_release(source: Path, cache: Path) -> None:
    manifest = cache / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes((source / ".claude-plugin" / "plugin.json").read_bytes())
    for directory in ("commands", "hooks", "pi", "skills"):
        target = cache / directory
        target.mkdir(parents=True)
        for file in (source / directory).iterdir():
            target.joinpath(file.name).write_bytes(file.read_bytes())


def _stub_cli(directory: Path) -> Path:
    directory.mkdir(parents=True)
    launcher = directory / "claude"
    launcher.write_text(
        """#!/bin/sh
set -eu
printf 'env HOME=%s CLAUDECODE=%s\\n' "$HOME" "${CLAUDECODE-}" >> "$ADW_STUB_LOG"
printf '%s\\n' "$*" >> "$ADW_STUB_LOG"
if [ "$1" = "plugin" ] && [ "$2" = "marketplace" ]; then
  mkdir -p "$ADW_STUB_CONFIG/plugins"
  printf '%s\\n' '{"agent-discipline-watcher":{"source":{"source":"directory","path":"'"$4"'"}}}' > "$ADW_STUB_CONFIG/plugins/known_marketplaces.json"
fi
if [ "$ADW_STUB_FAIL" = "1" ]; then
  exit 9
fi
if [ "$ADW_STUB_UPDATE_FAIL" = "1" ] && [ "$1" = "plugin" ] && [ "$2" = "update" ]; then
  exit 8
fi
if [ "$1" = "plugin" ] && [ "$2" = "install" -o "$2" = "update" ]; then
  mkdir -p "$ADW_STUB_CACHE"
  for tree in commands hooks pi skills; do
    mkdir -p "$ADW_STUB_CACHE/$tree"
    cp -R "$ADW_STUB_SOURCE/$tree/." "$ADW_STUB_CACHE/$tree/"
  done
  if [ "$ADW_STUB_BAD_COMMANDS" = "1" ]; then
    printf '%s' different > "$ADW_STUB_CACHE/commands/commands.txt"
  fi
  if [ "$ADW_STUB_BAD_MODE" = "1" ]; then
    chmod 0644 "$ADW_STUB_CACHE/hooks/hooks.txt"
  fi
  cp "$ADW_STUB_INSTALLED" "$ADW_STUB_CONFIG/plugins/installed_plugins.json"
  printf '%s\\n' '{"enabledPlugins":{"agent-discipline-watcher@agent-discipline-watcher":'"${ADW_STUB_ENABLED:-true}"'}}' > "$ADW_STUB_CONFIG/settings.json"
fi
exit 0
""",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _environment(home: Path, stub: Path, source: Path, cache: Path, installed: Path, log: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "PATH": str(stub.parent) + os.pathsep + os.defpath,
        "CLAUDECODE": "nested",
        "ADW_STUB_SOURCE": str(source),
        "ADW_STUB_CACHE": str(cache),
        "ADW_STUB_CONFIG": str(home / ".claude"),
        "ADW_STUB_INSTALLED": str(installed),
        "ADW_STUB_LOG": str(log),
        "ADW_STUB_FAIL": "0",
        "ADW_STUB_ENABLED": "true",
        "ADW_STUB_BAD_MODE": "0",
        "ADW_STUB_UPDATE_FAIL": "0",
        "ADW_STUB_BAD_COMMANDS": "0",
    }


def _scenario(
    tmp_path: Path,
    scope: str = "user",
    config_relative: Path = Path(".claude"),
) -> tuple[Path, Path, Path, Path, Path, dict[str, str]]:
    home = tmp_path / "home"
    home.mkdir()
    source = _staged_release(tmp_path / "release")
    config = _config(home, config_relative)
    cache = config / "plugins" / "cache" / "agent-discipline-watcher" / "agent-discipline-watcher" / COMMIT[:12]
    _copy_release(source, cache)
    installed = tmp_path / "installed.json"
    _installed(config, cache, COMMIT, scope=scope)
    installed.write_text((config / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"), encoding="utf-8")
    log = tmp_path / "calls.log"
    stub = _stub_cli(tmp_path / "bin")
    environment = _environment(home, stub, source, cache, installed, log)
    environment["ADW_STUB_CONFIG"] = str(config)
    return home, source, config, cache, log, environment


def test_installs_the_exact_commit_and_matches_the_staged_trees(tmp_path: Path) -> None:
    home, source, _config_root, cache, log, environment = _scenario(tmp_path)
    generated = cache / "hooks" / "__pycache__" / "generated.cpython-311.pyc"
    generated.parent.mkdir()
    generated.write_bytes(b"generated by the runtime")

    update_claude.install_pinned_plugin(home, source, COMMIT, environment)

    catalog_path = home / update_claude.MARKETPLACE_RELATIVE / ".claude-plugin" / "marketplace.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = next(plugin for plugin in catalog["plugins"] if plugin["name"] == update_claude.PLUGIN_NAME)
    assert entry["source"] == {"source": "github", "repo": REPOSITORY, "sha": COMMIT}
    assert generated.read_bytes() == b"generated by the runtime"
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("plugin marketplace add ") for line in calls)
    assert any(line.startswith("plugin update ") for line in calls)
    assert any("plugin install " in line or line.startswith("plugin update ") for line in calls)


def test_cli_environment_is_bound_to_the_requested_home(tmp_path: Path) -> None:
    home, source, _config_root, _cache, log, environment = _scenario(tmp_path)
    environment["HOME"] = str(tmp_path / "wrong-home")

    update_claude.install_pinned_plugin(home, source, COMMIT, environment)

    assert f"env HOME={home} CLAUDECODE=" in log.read_text(encoding="utf-8")
    assert json.loads((home / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]


def test_sole_native_config_profile_is_used(tmp_path: Path) -> None:
    home, source, config, _cache, _log, environment = _scenario(
        tmp_path,
        config_relative=Path(".config") / "claude-code",
    )

    update_claude.install_pinned_plugin(home, source, COMMIT, environment)

    assert (config / "plugins" / "installed_plugins.json").is_file()
    assert not (home / ".claude").exists()


def test_multiple_native_config_profiles_require_an_explicit_root(tmp_path: Path) -> None:
    home, source, _config_root, _cache, _log, environment = _scenario(tmp_path)
    _config(home, Path(".config") / "claude-code")

    with pytest.raises(ValueError, match="Use the Terminal installer with CLAUDE_CONFIG_DIR"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)

    assert not (home / update_claude.MARKETPLACE_RELATIVE).exists()


def test_bad_installed_commit_restores_the_previous_catalog_and_state(tmp_path: Path) -> None:
    home, source, config, cache, _log, environment = _scenario(tmp_path)
    catalog_path = home / update_claude.MARKETPLACE_RELATIVE / ".claude-plugin" / "marketplace.json"
    catalog_path.parent.mkdir(parents=True)
    previous_catalog = '{"name":"old","plugins":[]}\n'
    catalog_path.write_text(previous_catalog, encoding="utf-8")
    settings = config / "settings.json"
    settings.write_text(json.dumps({
        "enabledPlugins": {"unrelated@market": True},
        "extraKnownMarketplaces": {"unrelated": {"source": {"source": "directory", "path": "/other"}}},
        "unrelatedSetting": {"keep": True},
    }), encoding="utf-8")
    known = config / "plugins" / "known_marketplaces.json"
    known.write_text(json.dumps({"unrelated": {"source": {"source": "directory", "path": "/other"}}}), encoding="utf-8")
    installed_path = config / "plugins" / "installed_plugins.json"
    installed_path.write_text(json.dumps({"version": 2, "plugins": {"unrelated@market": [{"gitCommitSha": "dead"}]}}), encoding="utf-8")
    cache = cache.with_name("bad")
    installed = tmp_path / "installed.json"
    installed.write_text(json.dumps({
        "version": 2,
        "plugins": {update_claude.PLUGIN_ID: [{"gitCommitSha": "f" * 40, "installPath": str(cache)}]},
    }), encoding="utf-8")
    environment["ADW_STUB_CACHE"] = str(cache)
    with pytest.raises(RuntimeError, match="commit"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)

    assert catalog_path.read_text(encoding="utf-8") == previous_catalog
    restored_settings = json.loads(settings.read_text(encoding="utf-8"))
    assert restored_settings["enabledPlugins"] == {"unrelated@market": True}
    assert restored_settings["unrelatedSetting"] == {"keep": True}
    assert json.loads(known.read_text(encoding="utf-8")) == {"unrelated": {"source": {"source": "directory", "path": "/other"}}}
    assert json.loads(installed_path.read_text(encoding="utf-8"))["plugins"] == {"unrelated@market": [{"gitCommitSha": "dead"}]}


def test_invalid_commit_is_rejected_before_creating_the_catalog(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    source = _staged_release(tmp_path / "release")

    with pytest.raises(ValueError, match="40 hexadecimal"):
        update_claude.install_pinned_plugin(home, source, "short", {"PATH": "/missing"})

    assert not (home / update_claude.MARKETPLACE_RELATIVE).exists()


def test_atomic_json_preserves_a_zero_saved_mode(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    update_claude_state._atomic_write_json(path, {"state": True}, 0)

    assert stat.S_IMODE(path.stat().st_mode) == 0


def test_update_failure_falls_back_to_user_install(tmp_path: Path) -> None:
    home, source, _config_root, _cache, log, environment = _scenario(tmp_path)
    environment["ADW_STUB_UPDATE_FAIL"] = "1"

    update_claude.install_pinned_plugin(home, source, COMMIT, environment)

    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("plugin update ") for line in calls)
    assert any(line.startswith("plugin install ") for line in calls)


def test_matching_commit_is_rejected_when_the_plugin_is_disabled(tmp_path: Path) -> None:
    home, source, _config_root, _cache, _log, environment = _scenario(tmp_path)
    environment["ADW_STUB_ENABLED"] = "false"

    with pytest.raises(RuntimeError, match="enabled"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)


def test_matching_commit_in_a_project_entry_is_rejected(tmp_path: Path) -> None:
    home, source, _config_root, _cache, _log, environment = _scenario(tmp_path, scope="project")

    with pytest.raises(RuntimeError, match="commit"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)


def test_manifest_mismatch_is_rejected_even_when_runtime_trees_match(tmp_path: Path) -> None:
    home, source, _config_root, cache, _log, environment = _scenario(tmp_path)
    (cache / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "different-plugin"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="file mismatch"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)


def test_commands_tree_mismatch_is_rejected(tmp_path: Path) -> None:
    home, source, _config_root, _cache, _log, environment = _scenario(tmp_path)
    environment["ADW_STUB_BAD_COMMANDS"] = "1"

    with pytest.raises(RuntimeError, match="commands"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)


def test_commands_tree_symlink_is_rejected_in_the_staged_release(tmp_path: Path) -> None:
    home, source, _config_root, _cache, _log, environment = _scenario(tmp_path)
    link = source / "commands" / "linked.txt"
    link.symlink_to(source / "hooks" / "hooks.txt")

    with pytest.raises(ValueError, match="symlink"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)


def test_executable_mode_mismatch_is_rejected(tmp_path: Path) -> None:
    home, source, _config_root, _cache, _log, environment = _scenario(tmp_path)
    (source / "hooks" / "hooks.txt").chmod(0o755)
    environment["ADW_STUB_BAD_MODE"] = "1"

    with pytest.raises(RuntimeError, match="tree mismatch"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)


def test_symlinked_cache_ancestor_is_rejected(tmp_path: Path) -> None:
    home, source, config, _cache, _log, environment = _scenario(tmp_path)
    cache_root = config / "plugins" / "cache"
    shutil.rmtree(cache_root)
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    cache_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink"):
        update_claude.install_pinned_plugin(home, source, COMMIT, environment)
