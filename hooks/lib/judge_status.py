"""Split from the preset writer, because a stored preference and a running reviewer are two different facts."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

PLUGIN_ROOT_ENV = "CLAUDE_PLUGIN_ROOT"
CONFIG_ENV = "CLAUDE_CONFIG_DIR"
CACHE_PARTS = ("plugins", "cache", "agent-discipline-watcher", "agent-discipline-watcher")


def _load(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _count(document: dict, matches: Callable[[dict], bool]) -> int:
    groups = document.get("hooks")
    if not isinstance(groups, dict):
        return 0
    return sum(
        1
        for entries in groups.values()
        if isinstance(entries, list)
        for group in entries
        if isinstance(group, dict) and isinstance(group.get("hooks"), list)
        for entry in group["hooks"]
        if isinstance(entry, dict) and matches(entry)
    )


def plugin_reviewers(manifest_path: Path | None = None) -> int:
    """Read from the loaded plugin rather than this checkout, because a checkout answers yes on a machine with no install."""
    target = _installed_manifest() if manifest_path is None else manifest_path
    if target is None:
        return 0
    return _count(_load(target), lambda entry: entry.get("type") == "agent")


def _installed_manifest() -> Path | None:
    """Prefer the root Claude Code pinned, because that is the copy whose hooks actually run."""
    root = os.environ.get(PLUGIN_ROOT_ENV, "").strip()
    if root:
        candidate = Path(root) / "hooks" / "hooks.json"
        return candidate if candidate.is_file() else None
    newest: Path | None = None
    for cache in _cache_roots():
        for revision in sorted(cache.iterdir()) if cache.is_dir() else []:
            manifest = revision / "hooks" / "hooks.json"
            if manifest.is_file():
                newest = manifest
    return newest


def _cache_roots() -> tuple[Path, ...]:
    home = Path.home()
    override = os.environ.get(CONFIG_ENV, "").strip()
    roots = [Path(override)] if override else [home / ".config" / "claude-code", home / ".claude"]
    return tuple(root.joinpath(*CACHE_PARTS) for root in roots)


def settings_reviewers(settings_path: Path, is_managed: Callable[[object], bool]) -> int:
    """Counted separately, because a user who applied a preset carries reviewers the manifest never names."""
    return _count(_load(settings_path), is_managed)


def describe(preset: str, stored: bool, reviewers: int) -> dict[str, str]:
    """Reported as a count, because a preset naming a model that nothing runs still reads as working."""
    return {
        "preset": preset,
        "source": "stored" if stored else "default",
        "reviewers": str(reviewers),
        "judging": "yes" if reviewers else "no reviewer is registered, so only deterministic rules run",
    }
