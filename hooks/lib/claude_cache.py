"""Guarded by an exact path shape because a wipe that resolves one directory too high takes the user's whole config."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterator, NamedTuple


MARKETPLACE = "agent-discipline-watcher"
PLUGIN = "agent-discipline-watcher"
CONFIG_ENV = "CLAUDE_CONFIG_DIR"
CACHE_PARTS = ("plugins", "cache", MARKETPLACE, PLUGIN)
COMMAND_PARTS = ("commands", "adw")
INSTALLED_LEAF = ("plugins", "installed_plugins.json")


class NukeRefusal(RuntimeError):
    """Name the refusal because a silent skip would leave the stale cache the user asked to remove."""


class Target(NamedTuple):
    """Pair the path with its config root because a caller must report which tree it cleared."""

    config_root: Path
    path: Path


def config_roots(environment: dict[str, str] | None = None, home: Path | None = None) -> tuple[Path, ...]:
    """Search the same three places Claude Code does, because a user may have moved their config."""
    env = os.environ if environment is None else environment
    base = Path.home() if home is None else home
    candidates = [env.get(CONFIG_ENV, "").strip(), str(base / ".config" / "claude-code"), str(base / ".claude")]
    roots: list[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir() and path not in roots:
            roots.append(path)
    return tuple(roots)


def _guard(path: Path, config_root: Path, parts: tuple[str, ...]) -> None:
    """Check the tail rather than trusting the join, because one wrong variable moves the whole target."""
    if path.parts[-len(parts):] != parts:
        raise NukeRefusal(f"refusing to remove a path that is not the ADW cache: {path}")
    if path == config_root or config_root not in path.parents:
        raise NukeRefusal(f"refusing to remove a path outside the config root: {path}")
    if path.is_symlink():
        raise NukeRefusal(f"refusing to follow a symlink: {path}")


def removable(environment: dict[str, str] | None = None, home: Path | None = None) -> tuple[Target, ...]:
    """List before removing because a reader deciding needs to see every directory this clears."""
    found: list[Target] = []
    for root in config_roots(environment, home):
        for parts in (CACHE_PARTS, COMMAND_PARTS):
            path = root.joinpath(*parts)
            if not path.exists():
                continue
            _guard(path, root, parts)
            found.append(Target(root, path))
    return tuple(found)


def installed_revisions(environment: dict[str, str] | None = None, home: Path | None = None) -> tuple[str, ...]:
    """Read the cache directory names because ADW ships commit revisions rather than a version file."""
    names: list[str] = []
    for root in config_roots(environment, home):
        cache = root.joinpath(*CACHE_PARTS)
        if cache.is_dir():
            names.extend(sorted(entry.name for entry in cache.iterdir() if entry.is_dir()))
    return tuple(names)


def recorded_revision(environment: dict[str, str] | None = None, home: Path | None = None) -> str:
    """Prefer the recorded commit because two cache directories cannot say which one Claude Code loads."""
    for root in config_roots(environment, home):
        try:
            rows = json.loads(root.joinpath(*INSTALLED_LEAF).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for name, entries in rows.get("plugins", {}).items():
            if not name.startswith(f"{PLUGIN}@") or not isinstance(entries, list):
                continue
            for entry in entries:
                revision = entry.get("gitCommitSha") if isinstance(entry, dict) else None
                if isinstance(revision, str) and revision:
                    return revision
    return ""


def nuke(environment: dict[str, str] | None = None, home: Path | None = None) -> Iterator[Path]:
    """Remove the plugin cache alone, because the collector under the state directory holds the user's own settings."""
    for target in removable(environment, home):
        shutil.rmtree(target.path)
        yield target.path
