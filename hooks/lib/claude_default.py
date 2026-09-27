"""Split out, because claude_native is at its size gate."""
from __future__ import annotations

import sys

try:
    from . import claude_native, claude_presets
except ImportError:
    import claude_native
    import claude_presets

DEFAULT_PRESET = "haiku"


def ensure_default_block() -> str | None:
    """Only into an empty slot, because any block is a choice."""
    settings = claude_native._canonical(claude_native.settings_path())
    preset = claude_native._canonical(claude_native.preset_path())
    with claude_native._preset_lock(preset):
        claude_native._recover_unlocked(settings, preset)
        if claude_presets.managed_hooks(claude_native._load_settings(settings)):
            return None
        return claude_native._set_preset_unlocked(DEFAULT_PRESET, settings, preset)


def ensure_with_notice() -> None:
    """A notice, because a bad settings file must not end the session."""
    try:
        ensure_default_block()
    except (OSError, ValueError, RuntimeError) as exc:
        reason = " ".join(str(exc).split())
        sys.stderr.write(f"adw: Claude settings unreadable, no reviewer written: {reason}\n")
