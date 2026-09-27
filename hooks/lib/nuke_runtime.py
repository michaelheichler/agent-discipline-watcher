"""Built on the update footprint because a second list would drift."""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from . import update_runtime
from .update_runtime import HOSTS, INSTALL_PATH, MANAGED_LINKS, _check_path, _remove

NAME = "agent-discipline-watcher"
PLUGIN_ID = f"{NAME}@{NAME}"
REPO_DIR = Path(__file__).resolve().parents[2]
STATE_PATH = Path(".adw")
RC_START = "# >>> agent-discipline-watcher >>>"
RC_END = "# <<< agent-discipline-watcher <<<"
INSTALLED_RECORDS = Path("plugins/installed_plugins.json")
KNOWN_RECORDS = Path("plugins/known_marketplaces.json")
BACKUP_GLOBS = (f"config.toml.{NAME}.bak.*", f"hooks.json.{NAME}.bak.*")
GUARDED_PARTS = (("plugins", "cache", NAME), ("plugins", "marketplaces", NAME), ("commands", "adw"))
BIN_LINKS = frozenset(link for link in MANAGED_LINKS if link.startswith(".local/bin/"))
CLI_TIMEOUT_SECONDS = 180
RETRY = "Run again with --yes to remove them."
Render = Callable[[str], str]
Write = Callable[[Path, str], None]
JsonObject = dict[str, Any]
SettingsFilter = Callable[[JsonObject], JsonObject]
EditPair = tuple[Render, Write]


def _no_claude(_arguments: list[str], _environment: dict[str, str]) -> str:
    return "absent"


@dataclass(frozen=True, slots=True)
class NukeSteps:
    """Injected because a core module cannot import an adapter."""

    account_home: Callable[[], Path] = update_runtime._account_home
    environment: Callable[[], dict[str, str]] = lambda: dict(os.environ)
    claude_cache: ModuleType | None = None
    without_managed: SettingsFilter | None = None
    run_claude: Callable[[list[str], dict[str, str]], str] = _no_claude


@dataclass(frozen=True, slots=True)
class Edit:
    """Rendered twice because the claude CLI rewrites settings."""

    path: Path
    render: Render
    write: Write


@dataclass(slots=True)
class Plan:
    """Ordered because this script lives under ~/.adw."""

    records: list[Edit] = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)
    removals: list[Path] = field(default_factory=list)
    state: Path | None = None


@functools.cache
def _script(relative: str) -> ModuleType:
    """Loaded by path because the merge scripts have hyphens."""
    path = REPO_DIR / relative
    spec = importlib.util.spec_from_file_location(f"adw_nuke_{path.stem.replace('-', '_')}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the merge script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _codex_hooks() -> ModuleType:
    return _script("hooks/merge-codex-hooks.py")


def _codex_config() -> ModuleType:
    return _script("hooks/merge-codex-config.py")


def _claude_settings() -> ModuleType:
    return _script("hooks/merge-claude-settings.py")


def _omp_settings() -> ModuleType:
    return _script("pi/merge-settings.py")


def _json_object(text: str, path_hint: str) -> dict[str, Any]:
    value = json.loads(text) if text.strip() else {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{path_hint} is not a JSON object")
    return value


RC_BLOCK = re.compile(rf"^[^\n]*{re.escape(RC_START)}.*?{re.escape(RC_END)}[^\n]*(?:\n|\Z)", re.M | re.S)


def strip_rc_block(text: str) -> str:
    """Needs both fences, because an open one may hide user lines."""
    return RC_BLOCK.sub("", text)


def strip_codex_hooks(text: str) -> str:
    """Per handler, because a user group may share an event."""
    current = _json_object(text, "Codex hooks.json")
    hooks = current.get("hooks")
    if not isinstance(hooks, dict):
        return text
    before = json.dumps(current)
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept = [rest for group in groups if (rest := _codex_hooks().without_watcher_handlers(group)) is not None]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return text if json.dumps(current) == before else json.dumps(current, indent=2) + "\n"


def strip_codex_config(text: str) -> str:
    """Validated because a broken TOML stops Codex from starting."""
    merger = _codex_config()
    stripped = merger.strip_legacy_tables(merger.strip_fences(text))
    if stripped != text:
        merger.validate_toml(stripped)
        merger.validate_preserved_sections(text, stripped)
    return stripped


def _drop_member(value: JsonObject, section: str, key: str) -> None:
    members = value.get(section)
    if isinstance(members, dict) and key in members:
        del members[key]
        if not members:
            del value[section]


def strip_claude_settings(text: str, without_managed: SettingsFilter | None) -> str:
    """Pruned twice because older installs wrote path hooks."""
    merger = _claude_settings()
    original = _json_object(text, "Claude settings.json")
    cleaned = merger.prune(without_managed(dict(original)) if without_managed else original)
    if cleaned is merger.DROP:
        cleaned = {}
    merger._drop_emptied_lifecycles(original, cleaned)
    _drop_member(cleaned, "enabledPlugins", PLUGIN_ID)
    _drop_member(cleaned, "extraKnownMarketplaces", NAME)
    return text if cleaned == original else json.dumps(cleaned, indent=2, sort_keys=True) + "\n"


def strip_omp_settings(text: str, skill_dir: Path) -> str:
    """Matched like pi/install.sh --remove, to keep other extensions."""
    settings = _json_object(text, "OMP settings.json")
    entries = settings.get("extensions")
    if not isinstance(entries, list):
        return text
    kept = [entry for entry in entries if not _omp_settings().is_watcher_entry(entry, skill_dir)]
    if len(kept) == len(entries):
        return text
    if kept:
        settings["extensions"] = kept
    else:
        del settings["extensions"]
    return json.dumps(settings, indent=2, sort_keys=True) + "\n"


def strip_installed_records(text: str) -> str:
    registry = _json_object(text, "installed_plugins.json")
    plugins = registry.get("plugins")
    if not isinstance(plugins, dict) or PLUGIN_ID not in plugins:
        return text
    del plugins[PLUGIN_ID]
    return json.dumps(registry, indent=2) + "\n"


def strip_known_records(text: str) -> str:
    registry = _json_object(text, "known_marketplaces.json")
    if NAME not in registry:
        return text
    del registry[NAME]
    return json.dumps(registry, indent=2) + "\n"


def _write_claude_settings(path: Path, text: str) -> None:
    _claude_settings()._write(path, json.loads(text))


def _write_with(loader: Callable[[], ModuleType]) -> Write:
    return lambda path, text: loader().atomic_write(path, text)


def _fixed_edits(home: Path) -> dict[str, EditPair]:
    rc = (strip_rc_block, _write_with(_codex_hooks))
    omp = functools.partial(strip_omp_settings, skill_dir=home / INSTALL_PATH)
    return {
        ".zshrc": rc, ".bashrc": rc,
        ".codex/hooks.json": (strip_codex_hooks, _write_with(_codex_hooks)),
        ".codex/config.toml": (strip_codex_config, _write_with(_codex_config)),
        ".omp/agent/settings.json": (omp, _write_with(_omp_settings)),
    }


def _profile_edits(steps: NukeSteps) -> dict[str, EditPair]:
    claude = functools.partial(strip_claude_settings, without_managed=steps.without_managed)
    return {
        "settings.json": (claude, _write_claude_settings),
        INSTALLED_RECORDS.name: (strip_installed_records, _write_with(_codex_hooks)),
        KNOWN_RECORDS.name: (strip_known_records, _write_with(_codex_hooks)),
    }


def _edit_for(path: Path, home: Path, steps: NukeSteps) -> Edit | None:
    pair = _fixed_edits(home).get(path.relative_to(home).as_posix()) or _profile_edits(steps).get(path.name)
    return Edit(path, *pair) if pair else None


def _inside(path: Path, home: Path) -> None:
    if path == home or home not in path.parents:
        raise RuntimeError(f"refusing a path outside the home directory: {path}")


def _claude_roots(home: Path, steps: NukeSteps) -> tuple[Path, ...]:
    """Checked first because a symlinked root redirects every write."""
    if steps.claude_cache is None:
        return ()
    roots = tuple(steps.claude_cache.config_roots(steps.environment(), home))
    for root in roots:
        _inside(root, home)
        _check_path(root, home)
    return roots


def _footprint(home: Path, roots: tuple[Path, ...]) -> list[Path]:
    """Drawn from _selected_paths because a second list drifts."""
    paths: list[Path] = []
    for root in roots or (home / ".claude",):
        paths.extend(update_runtime._selected_paths(home, HOSTS, root))
        paths.append(root.joinpath(*GUARDED_PARTS[-1]))
    for pattern in BACKUP_GLOBS:
        paths.extend(sorted((home / ".codex").glob(pattern)))
    return list(dict.fromkeys(paths))


def _owned_link(path: Path, home: Path) -> bool:
    """Matched on target, because another tool may own the name."""
    if not path.is_symlink():
        return False
    target = os.readlink(path)
    landing = Path(os.path.abspath(path.parent / target))
    return f"/{NAME}/" in f"{target}/" or landing.is_relative_to(home / STATE_PATH)


@dataclass(frozen=True, slots=True)
class Scope:
    """Bundled because every planning step needs all three."""

    home: Path
    roots: tuple[Path, ...]
    steps: NukeSteps


def _guard_plugin_dir(path: Path, scope: Scope) -> None:
    matches = [(root, parts) for root in scope.roots for parts in GUARDED_PARTS if path == root.joinpath(*parts)]
    for root, parts in matches:
        scope.steps.claude_cache._guard(path, root, parts)


def _check_removal(path: Path, scope: Scope) -> None:
    """Called before any write because a late stop leaves half a wipe."""
    link = path.is_symlink()
    relative = path.relative_to(scope.home).as_posix()
    if (link or relative in BIN_LINKS) and not _owned_link(path, scope.home):
        raise RuntimeError(f"refusing a foreign link path: {path}")
    _guard_plugin_dir(path, scope)
    _check_path(path, scope.home, allow_link=link)


def _pending(edit: Edit, home: Path) -> bool:
    """Guarded only when changed, because a clean dotfile is harmless."""
    if not edit.path.is_file():
        return False
    text = edit.path.read_text(encoding="utf-8")
    if edit.render(text) == text:
        return False
    _check_path(edit.path, home)
    return True


def _is_state(path: Path, home: Path) -> bool:
    return path == home / STATE_PATH or home / STATE_PATH in path.parents


def _plan_path(plan: Plan, path: Path, scope: Scope) -> None:
    _inside(path, scope.home)
    edit = _edit_for(path, scope.home, scope.steps)
    if _is_state(path, scope.home):
        return
    if edit is not None:
        if _pending(edit, scope.home):
            (plan.records if path.parent.name == "plugins" else plan.edits).append(edit)
    elif os.path.lexists(path):
        _check_removal(path, scope)
        plan.removals.append(path)


def build_plan(home: Path, steps: NukeSteps) -> Plan:
    """Planned in full first because a refusal must write nothing."""
    scope = Scope(home, _claude_roots(home, steps), steps)
    plan = Plan()
    for path in _footprint(home, scope.roots):
        _plan_path(plan, path, scope)
    if os.path.lexists(home / STATE_PATH):
        _check_path(home / STATE_PATH, home)
        plan.state = home / STATE_PATH
    return plan


def plan_lines(plan: Plan) -> list[str]:
    lines = [f"edit {edit.path}" for edit in (*plan.records, *plan.edits)]
    lines.extend(f"remove {path}" for path in plan.removals)
    if plan.state is not None:
        lines.append(f"remove {plan.state}")
    return lines


def run_claude(arguments: list[str], environment: dict[str, str]) -> str:
    """Named outcome because the fallback must say why it ran."""
    binary = shutil.which("claude", path=environment.get("PATH"))
    if binary is None:
        return "absent"
    try:
        result = subprocess.run(
            [binary, *arguments], cwd=environment.get("HOME"), env=environment, capture_output=True,
            text=True, check=False, timeout=CLI_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return "failed"
    return "ok" if result.returncode == 0 else "failed"


def _unregister(root: Path, home: Path, steps: NukeSteps) -> str:
    """CLAUDECODE unset because Claude refuses a nested session."""
    environment = {**steps.environment(), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(root)}
    environment.pop("CLAUDECODE", None)
    commands = (["plugin", "uninstall", PLUGIN_ID], ["plugin", "marketplace", "remove", NAME])
    outcomes = [steps.run_claude(command, environment) for command in commands]
    return next((outcome for outcome in outcomes if outcome != "ok"), "ok")


def _apply(edit: Edit) -> bool:
    if not edit.path.is_file():
        return False
    text = edit.path.read_text(encoding="utf-8")
    rendered = edit.render(text)
    if rendered == text:
        return False
    edit.write(edit.path, rendered)
    return True


FALLBACK_REASONS = {"ok": "left the record behind", "absent": "is not installed", "failed": "failed"}


def _drop_records(plan: Plan, home: Path, steps: NukeSteps) -> list[Path]:
    """Run first because the claude binary needs the plugin present."""
    edited: list[Path] = []
    for root in dict.fromkeys(edit.path.parent.parent for edit in plan.records):
        edits = [edit for edit in plan.records if edit.path.parent.parent == root]
        route = _unregister(root, home, steps)
        direct = [edit.path for edit in edits if _apply(edit)]
        if route == "ok" and not direct:
            print(f"claude CLI removed the plugin records in {root}")
        for path in direct:
            print(f"edited {path} directly because the claude CLI {FALLBACK_REASONS[route]}")
        edited.extend(edit.path for edit in edits)
    return edited


def execute(plan: Plan, home: Path, steps: NukeSteps) -> list[Path]:
    """State goes last because this script runs from under it."""
    edited = _drop_records(plan, home, steps)
    for edit in plan.edits:
        if _apply(edit):
            print(f"edited {edit.path}")
            edited.append(edit.path)
    for path in (*plan.removals, *([plan.state] if plan.state else [])):
        if os.path.lexists(path):
            _remove(path)
            print(f"removed {path}")
    return edited


def _closing(edited: list[Path]) -> None:
    print("Edited config files:" if edited else "Edited no config files.")
    for path in edited:
        print(f"  {path}")
    print("Restart Claude Code, Codex, and OMP, then run ./install.sh from a checkout.")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="adw-nuke", allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--yes", action="store_true")
    return parser.parse_args(sys.argv[1:] if argv is None else argv)


def _preview(lines: list[str], dry_run: bool) -> int:
    for line in lines:
        print(line)
    if dry_run:
        return 0
    print(RETRY)
    return 2


def main(argv: list[str] | None = None, *, steps: NukeSteps = NukeSteps()) -> int:
    """Gated on --yes because the wipe has no undo."""
    args = _arguments(argv)
    try:
        home = steps.account_home()
        plan = build_plan(home, steps)
        lines = plan_lines(plan)
        if not lines:
            print("Nothing of ADW is left on this machine.")
            return 0
        if not args.yes:
            return _preview(lines, args.dry_run)
        _closing(execute(plan, home, steps))
        return 0
    except Exception as error:
        print(f"adw-nuke stopped: {error}", file=sys.stderr)
        return 2
