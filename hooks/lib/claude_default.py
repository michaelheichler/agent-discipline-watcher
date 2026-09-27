"""Split out, because claude_native is at its size gate."""
from __future__ import annotations

import copy
import json
import re
import shlex
import sys
from typing import Any

try:
    from . import claude_native, claude_presets
except ImportError:
    import claude_native
    import claude_presets

DEFAULT_PRESET = "haiku"
SCRIPT_TOKEN = re.compile(r"'[^']*/hooks/(?:read_claude_journal|claude_luna)\.sh'|/[^\s']*/hooks/(?:read_claude_journal|claude_luna)\.sh")


def _current_token(token: str) -> str:
    leaf = shlex.split(token)[0].rsplit("/", 1)[1]
    return shlex.quote(str(claude_presets.PLUGIN_ROOT / "hooks" / leaf))


def _repointed_text(text: str) -> str:
    return SCRIPT_TOKEN.sub(lambda match: _current_token(match.group(0)), text)


def _repoint_hook(hook: dict[str, Any]) -> None:
    field = "prompt" if hook.get("type") == "agent" else "command"
    hook[field] = _repointed_text(hook[field])


def _hook_entries(settings: dict[str, Any]) -> list[object]:
    lifecycles = settings.get("hooks")
    groups = [
        group
        for entries in (lifecycles.values() if isinstance(lifecycles, dict) else [])
        if isinstance(entries, list)
        for group in entries
        if isinstance(group, dict) and isinstance(group.get("hooks"), list)
    ]
    return [hook for group in groups for hook in group["hooks"]]


def _repointed(settings: dict[str, Any]) -> dict[str, Any]:
    """Paths only, because the rest may be a user edit."""
    updated = copy.deepcopy(settings)
    for hook in _hook_entries(updated):
        if claude_presets.is_managed_hook(hook):
            _repoint_hook(hook)
    return updated


def _repoint_block(settings_path: Any) -> None:
    digest, current, generation = claude_native._settings_snapshot(settings_path)
    updated = _repointed(current)
    if updated == current:
        return
    rendered = json.dumps(updated, indent=2, sort_keys=True) + "\n"
    claude_native._atomic_write_settings(settings_path, rendered, expected_generation=(digest, generation))


def ensure_default_block() -> str | None:
    """Only into an empty slot, because any block is a choice."""
    settings = claude_native._canonical(claude_native.settings_path())
    preset = claude_native._canonical(claude_native.preset_path())
    with claude_native._preset_lock(preset):
        claude_native._recover_unlocked(settings, preset)
        if claude_presets.managed_hooks(claude_native._load_settings(settings)):
            _repoint_block(settings)
            return None
        return claude_native._set_preset_unlocked(DEFAULT_PRESET, settings, preset)


def ensure_with_notice() -> None:
    """A notice, because a bad settings file must not end the session."""
    try:
        ensure_default_block()
    except (OSError, ValueError, RuntimeError) as exc:
        reason = " ".join(str(exc).split())
        sys.stderr.write(f"adw: Claude settings unreadable, no reviewer written: {reason}\n")
