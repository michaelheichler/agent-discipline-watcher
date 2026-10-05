"""Seed or repoint the block, because the plugin ships none."""
from __future__ import annotations

import copy
import re
import shlex
import sys
from pathlib import Path
from typing import Any

try:
    from . import claude_native, claude_presets
except ImportError:
    import claude_native
    import claude_presets

SCRIPT_TOKEN = re.compile(r"'[^']*/hooks/claude_(?:luna|sonnet)\.sh'|/[^\s']*/hooks/claude_(?:luna|sonnet)\.sh")


def _current_token(token: str) -> str:
    leaf = shlex.split(token)[0].rsplit("/", 1)[1]
    return shlex.quote(str(claude_presets.handler_root() / "hooks" / leaf))


def _repointed_text(text: str) -> str:
    return SCRIPT_TOKEN.sub(lambda match: _current_token(match.group(0)), text)


def _repoint_hook(hook: dict[str, Any]) -> None:
    hook["command"] = _repointed_text(hook["command"])


def _repointed(settings: dict[str, Any]) -> dict[str, Any]:
    """Paths only, because the rest may be a user edit."""
    updated = copy.deepcopy(settings)
    for _lifecycle, hook in claude_presets.hook_entries(updated):
        if claude_presets.is_managed_hook(hook):
            _repoint_hook(hook)
    return updated


def ensure_default_block(settings_path: str | Path | None = None, preset_path: str | Path | None = None) -> str | None:
    """Into an empty slot or over a retired agent block, because any other block is a choice."""
    preset = claude_native.default_preset(preset_path=preset_path, settings_path=settings_path)
    return claude_native.ensure_managed_block(
        preset, _repointed, claude_presets.has_retired_agent_hook,
        settings_path=settings_path, preset_path=preset_path,
    )


def ensure_with_notice() -> None:
    """A notice, because a bad settings file must not end the session."""
    try:
        ensure_default_block()
    except (OSError, ValueError, RuntimeError) as exc:
        reason = " ".join(str(exc).split())
        sys.stderr.write(f"adw: Claude settings unreadable, no reviewer written: {reason}\n")
