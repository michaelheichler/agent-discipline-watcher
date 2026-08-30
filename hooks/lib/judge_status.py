"""Split from the preset writer, because a stored preference and a running reviewer are two different facts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_MANIFEST = PLUGIN_ROOT / "hooks" / "hooks.json"


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
    """Read from the shipped manifest, because installing the plugin is the whole setup for a default user."""
    document = _load(PLUGIN_MANIFEST if manifest_path is None else manifest_path)
    return _count(document, lambda entry: entry.get("type") == "agent")


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
