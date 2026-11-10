"""Split from the preset writer, because a stored preference and a running reviewer are two different facts."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from . import config_roots
except ImportError:
    import config_roots
from typing import Callable

PLUGIN_ROOT_ENV = "CLAUDE_PLUGIN_ROOT"
CONFIG_ENV = config_roots.CLAUDE_CONFIG_ENV


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
    """Kept, because an old cached plugin still ships agents."""
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
    for root in config_roots.claude_config_roots():
        cache = root.joinpath(*config_roots.CLAUDE_CACHE_PARTS)
        for revision in sorted(cache.iterdir()) if cache.is_dir() else []:
            manifest = revision / "hooks" / "hooks.json"
            if manifest.is_file():
                newest = manifest
    return newest


def settings_reviewers(settings_path: Path, is_managed: Callable[[object], bool]) -> int:
    """Counted here, because settings hold the only reviewer."""
    return _count(_load(settings_path), is_managed)


def describe(preset: str, stored: bool, reviewers: int) -> dict[str, str]:
    """Reported as a count, because a preset naming a model that nothing runs still reads as working."""
    return {
        "preset": preset,
        "source": "stored" if stored else "default",
        "reviewers": str(reviewers),
        "judging": "yes" if reviewers else "no reviewer is registered, so only deterministic rules run",
    }
