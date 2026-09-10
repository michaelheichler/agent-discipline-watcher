from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from install_runtime import EXCLUDED_NAMES

try:
    from . import update_claude_state as state
except ImportError:
    import update_claude_state as state


MARKETPLACE_NAME = "agent-discipline-watcher"
PLUGIN_NAME = "agent-discipline-watcher"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
REPOSITORY = "michaelheichler/agent-discipline-watcher"
MARKETPLACE_RELATIVE = Path(".adw") / "update-marketplace"
CONFIG_ENV = "CLAUDE_CONFIG_DIR"
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
TREES_TO_VERIFY = ("hooks", "pi", "skills")
FILES_TO_VERIFY = (Path(".claude-plugin") / "plugin.json",)
CLI_TIMEOUT_SECONDS = 180


def install_pinned_plugin(
    home: Path,
    source: Path,
    commit: str,
    environment: dict[str, str],
) -> None:
    target_home = _directory(Path(home), "home")
    staged_source = _directory(Path(source), "staged release")
    pinned_commit = _commit(commit)
    _validate_source(staged_source)

    cli_environment = _cli_environment(target_home, environment)
    config_root = _config_root(target_home, cli_environment)
    catalog_path = target_home / MARKETPLACE_RELATIVE / ".claude-plugin" / "marketplace.json"
    snapshots = state.snapshots(config_root, catalog_path)

    try:
        _write_catalog(catalog_path, pinned_commit)
        _register_marketplace(target_home, catalog_path.parent.parent, cli_environment)
        _install_plugin(target_home, config_root, cli_environment)
        _verify_registration(config_root, catalog_path.parent.parent)
        _verify_install(target_home, config_root, staged_source, pinned_commit)
    except BaseException as error:
        try:
            state.rollback(config_root, catalog_path, snapshots, MARKETPLACE_NAME, PLUGIN_ID)
        except BaseException as rollback_error:
            raise RuntimeError(f"Claude plugin update failed and rollback failed: {rollback_error}") from error
        raise


def _commit(value: str) -> str:
    if not isinstance(value, str) or not COMMIT_PATTERN.fullmatch(value):
        raise ValueError("commit must be exactly 40 hexadecimal characters")
    return value.lower()


def _directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {path}")
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return Path(os.path.abspath(path))


def _validate_source(source: Path) -> None:
    _reject_symlinks(source / ".claude-plugin")
    manifest = source / ".claude-plugin" / "plugin.json"
    if not os.path.lexists(manifest) or manifest.is_symlink() or not manifest.is_file():
        raise ValueError(f"staged plugin manifest is not a regular file: {manifest}")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"staged plugin manifest is not valid JSON: {manifest}") from error
    if not isinstance(value, dict) or value.get("name") != PLUGIN_NAME:
        raise ValueError(f"staged plugin manifest names a different plugin: {manifest}")
    hooks = source / "hooks"
    if not hooks.is_dir() or hooks.is_symlink():
        raise ValueError(f"staged release has no safe hooks tree: {hooks}")
    for name in TREES_TO_VERIFY:
        _reject_symlinks(source / name)


def _reject_symlinks(root: Path) -> None:
    if not os.path.lexists(root):
        return
    if root.is_symlink():
        raise ValueError(f"staged release contains a symlink: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"staged release contains a symlink: {path}")


def _cli_environment(home: Path, environment: Mapping[str, str]) -> dict[str, str]:
    result = {str(key): str(value) for key, value in environment.items()}
    result["HOME"] = str(home)
    result.pop("CLAUDECODE", None)
    result.pop("ADW_SKIP_PLUGIN", None)
    result[CONFIG_ENV] = str(_config_root(home, result))
    return result


def _config_root(home: Path, environment: Mapping[str, str]) -> Path:
    raw = str(environment.get(CONFIG_ENV, "")).strip()
    if raw == "~":
        candidate = home
    elif raw.startswith("~/"):
        candidate = home / raw[2:]
    else:
        candidate = Path(raw) if raw else home / ".claude"
    if not candidate.is_absolute():
        candidate = home / candidate
    target = Path(os.path.abspath(candidate))
    if not _within(target, home):
        raise ValueError(f"Claude config directory is outside the requested home: {target}")
    _reject_path_symlinks(target, home)
    return target


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _reject_path_symlinks(path: Path, parent: Path) -> None:
    current = parent
    for part in path.relative_to(parent).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"state path must not contain a symlink: {current}")


def _catalog(commit: str) -> dict[str, Any]:
    return {
        "$schema": "https://www.schemastore.org/claude-code-marketplace.json",
        "name": MARKETPLACE_NAME,
        "description": "Single-plugin marketplace for the Agent Discipline Watcher hook package.",
        "owner": {"name": "Michael Heichler"},
        "plugins": [{
            "name": PLUGIN_NAME,
            "description": "Deterministic discipline gates for agent output and edits.",
            "source": {"source": "github", "repo": REPOSITORY, "sha": commit},
            "category": "productivity",
        }],
    }


def _write_catalog(path: Path, commit: str) -> None:
    state.mkdir_safe(path.parent)
    state.atomic_write(path, (json.dumps(_catalog(commit), indent=2, sort_keys=True) + "\n").encode(), 0o600)


def _run_cli(home: Path, args: list[str], environment: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("claude", path=environment.get("PATH")) or "claude"
    try:
        result = subprocess.run(
            [binary, *args],
            cwd=home,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=CLI_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Claude CLI failed to run: {error}") from error
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        detail = f": {output[:400]}" if output else ""
        raise RuntimeError(f"Claude CLI command failed ({' '.join(args)}){detail}")
    return result


def _register_marketplace(home: Path, marketplace_root: Path, environment: Mapping[str, str]) -> None:
    try:
        _run_cli(home, ["plugin", "marketplace", "add", str(marketplace_root)], environment)
    except RuntimeError as add_error:
        try:
            _run_cli(home, ["plugin", "marketplace", "update", MARKETPLACE_NAME], environment)
        except RuntimeError as update_error:
            raise RuntimeError(f"Claude marketplace registration failed: {update_error}") from add_error


def _install_plugin(home: Path, config_root: Path, environment: Mapping[str, str]) -> None:
    plugin = ["plugin", "update", PLUGIN_ID] if _user_plugin_installed(config_root) else [
        "plugin", "install", PLUGIN_ID, "--scope", "user", "--yes",
    ]
    try:
        _run_cli(home, plugin, environment)
        return
    except RuntimeError as first_error:
        if plugin[2] != "update":
            raise
        try:
            _run_cli(
                home,
                ["plugin", "install", PLUGIN_ID, "--scope", "user", "--yes"],
                environment,
            )
        except RuntimeError as install_error:
            raise RuntimeError(f"Claude plugin update and install failed: {install_error}") from first_error


def _user_plugin_installed(config_root: Path) -> bool:
    try:
        registry = _read_json(config_root / "plugins" / "installed_plugins.json")
    except RuntimeError:
        return False
    plugins = registry.get("plugins")
    entries = plugins.get(PLUGIN_ID) if isinstance(plugins, dict) else None
    return isinstance(entries, list) and any(
        isinstance(entry, dict) and entry.get("scope") == "user" for entry in entries
    )


def _verify_registration(config_root: Path, marketplace_root: Path) -> None:
    registry = _read_json(config_root / "plugins" / "known_marketplaces.json")
    entry = registry.get(MARKETPLACE_NAME)
    source = entry.get("source") if isinstance(entry, dict) else None
    expected = {"source": "directory", "path": str(marketplace_root)}
    if source != expected:
        raise RuntimeError(f"Claude marketplace is not registered from the pinned catalog: {marketplace_root}")
    settings = _read_json(config_root / "settings.json")
    extra = settings.get("extraKnownMarketplaces")
    if isinstance(extra, dict) and MARKETPLACE_NAME in extra:
        extra_entry = extra[MARKETPLACE_NAME]
        extra_source = extra_entry.get("source") if isinstance(extra_entry, dict) else None
        if extra_source != expected:
            raise RuntimeError(f"Claude settings point the marketplace elsewhere: {marketplace_root}")


def _verify_install(home: Path, config_root: Path, source: Path, commit: str) -> None:
    registry_path = config_root / "plugins" / "installed_plugins.json"
    registry = _read_json(registry_path)
    plugins = registry.get("plugins") if isinstance(registry, dict) else None
    entries = plugins.get(PLUGIN_ID) if isinstance(plugins, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError(f"Claude plugin registry has no {PLUGIN_ID} entry")
    matching = [
        entry for entry in entries
        if isinstance(entry, dict)
        and entry.get("scope") == "user"
        and str(entry.get("gitCommitSha", "")).lower() == commit
    ]
    if not matching:
        raise RuntimeError(f"Claude plugin registry does not record commit {commit}")
    install_path = matching[-1].get("installPath")
    if not isinstance(install_path, str) or not install_path:
        raise RuntimeError("Claude plugin registry entry has no install path")
    cache = _expand_install_path(install_path, home)
    if not cache.is_absolute():
        cache = config_root / cache
    cache = Path(os.path.abspath(cache))
    cache_root = config_root / "plugins" / "cache"
    if not _within(cache, cache_root) or cache == cache_root:
        raise RuntimeError(f"Claude plugin install path is outside its cache: {cache}")
    try:
        _reject_path_symlinks(cache, config_root)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    if cache.is_symlink() or not cache.is_dir():
        raise RuntimeError(f"Claude plugin cache is not a directory: {cache}")
    _compare_release_trees(source, cache)
    _verify_enabled(config_root)


def _expand_install_path(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    return Path(value)


def _verify_enabled(config_root: Path) -> None:
    settings = _read_json(config_root / "settings.json")
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict) or enabled.get(PLUGIN_ID) is not True:
        raise RuntimeError(f"Claude plugin is not enabled: {PLUGIN_ID}")


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Claude state file is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Claude state file is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Claude state file is not a JSON object: {path}")
    return value


def _compare_release_trees(source: Path, cache: Path) -> None:
    for relative in FILES_TO_VERIFY:
        if not _same_tree(source / relative, cache / relative):
            raise RuntimeError(f"Claude plugin cache file mismatch: {relative}")
    for name in TREES_TO_VERIFY:
        expected = source / name
        actual = cache / name
        expected_exists = os.path.lexists(expected)
        actual_exists = os.path.lexists(actual)
        if expected_exists != actual_exists:
            raise RuntimeError(f"Claude plugin cache tree mismatch: {name}")
        if expected_exists and not _same_tree(expected, actual):
            raise RuntimeError(f"Claude plugin cache tree mismatch: {name}")


def _same_tree(expected: Path, actual: Path) -> bool:
    if expected.is_symlink() or actual.is_symlink():
        return False
    expected_kind = _tree_kind(expected)
    actual_kind = _tree_kind(actual)
    if expected_kind != actual_kind:
        return False
    if expected_kind == "file":
        return _same_file(expected, actual)
    if expected_kind != "directory":
        return False
    return _same_directory(expected, actual)


def _tree_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"


def _same_file(expected: Path, actual: Path) -> bool:
    try:
        expected_mode = expected.stat().st_mode & 0o111
        actual_mode = actual.stat().st_mode & 0o111
        return expected_mode == actual_mode and expected.read_bytes() == actual.read_bytes()
    except OSError:
        return False


def _same_directory(expected: Path, actual: Path) -> bool:
    try:
        expected_children = {
            path.name: path for path in expected.iterdir() if path.name not in EXCLUDED_NAMES
        }
        actual_children = {
            path.name: path for path in actual.iterdir() if path.name not in EXCLUDED_NAMES
        }
    except OSError:
        return False
    if expected_children.keys() != actual_children.keys():
        return False
    return all(_same_tree(expected_children[name], actual_children[name]) for name in expected_children)
