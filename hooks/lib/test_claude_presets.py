from __future__ import annotations

import pytest

from lib import claude_native, claude_presets


@pytest.mark.parametrize("retired", ("haiku", "luna-native", "mixed", "sonnet"))
def test_a_retired_preset_is_refused(retired: str) -> None:
    """Refuse it by name because an old settings file may still ask for it."""
    with pytest.raises(ValueError):
        claude_presets.validate_preset(retired)


@pytest.mark.parametrize("retired", ("haiku", "luna-native", "mixed", "sonnet"))
def test_a_stored_retired_preset_reads_as_the_preset_that_replaced_it(tmp_path, retired: str) -> None:
    """Map it because a dropped name reads as no preset, and status would then report a default while a retired reviewer runs."""
    stored = tmp_path / "preset"
    stored.write_text(f"{retired}\n", encoding="utf-8")

    assert claude_native.read_preset(stored, settings_path=tmp_path / "settings.json") == "luna"


@pytest.mark.parametrize("preset", claude_presets.PRESETS)
def test_no_preset_registers_an_agent_hook(preset: str) -> None:
    """Command only, because an agent hook runs in don't-ask mode and cannot run a Bash helper."""
    types = {
        hook["type"]
        for groups in claude_presets.generated_hooks(preset).values()
        for group in groups
        for hook in group["hooks"]
    }

    assert types == {"command"}


def test_the_luna_preset_registers_a_command_on_both_events() -> None:
    """Register a command because python reaches Luna through the SDK rather than through the host."""
    generated = claude_presets.generated_hooks("luna")

    assert generated["PostToolUse"][0]["hooks"][0]["command"] == claude_presets.luna_command()
    assert generated["Stop"][0]["hooks"][0]["command"] == claude_presets.luna_command()


@pytest.mark.parametrize("preset", claude_presets.PRESETS)
def test_no_preset_registers_a_handler_on_pre_tool_use(preset: str) -> None:
    """Stay off PreToolUse because a non-conforming reply there denies the tool call, reproduced in f9da7d5."""
    assert "PreToolUse" not in claude_presets.generated_hooks(preset)


@pytest.mark.parametrize("preset", claude_presets.PRESETS)
def test_every_generated_handler_is_recognised_as_managed(preset: str) -> None:
    """Mark them because a second merge duplicates any entry the merger cannot recognise as ours."""
    entries = [
        hook
        for groups in claude_presets.generated_hooks(preset).values()
        for group in groups
        for hook in group["hooks"]
    ]

    assert entries
    assert all(claude_presets.is_managed_hook(entry) for entry in entries)


@pytest.mark.parametrize("preset", claude_presets.PRESETS)
def test_every_handler_names_its_script_by_absolute_path(preset: str) -> None:
    """Absolute, because settings hooks get no plugin root."""
    commands = [
        hook["command"]
        for groups in claude_presets.generated_hooks(preset).values()
        for group in groups
        for hook in group["hooks"]
    ]

    assert commands
    assert all("CLAUDE_PLUGIN_ROOT" not in command and "/hooks/claude_" in command for command in commands)


def test_a_retired_agent_hook_still_counts_as_managed_and_as_retired() -> None:
    """Keep recognising it because a settings file written before the change must be cleaned, not left to fail."""
    agent = {"type": "agent", "model": "haiku", "prompt": f"{claude_presets.MANAGED_MARKER}\nreview"}
    settings = {"hooks": {"Stop": [{"hooks": [agent]}]}}

    assert claude_presets.is_managed_hook(agent)
    assert claude_presets.has_retired_hook(settings)
    assert claude_presets.without_managed(settings)["hooks"] == {}


def test_an_agent_hook_without_the_marker_is_not_retired() -> None:
    """Leave it alone because it belongs to the user."""
    foreign = {"type": "agent", "model": "haiku", "prompt": "someone else's reviewer"}

    assert not claude_presets.has_retired_hook({"hooks": {"Stop": [{"hooks": [foreign]}]}})


def test_a_luna_command_block_is_not_retired() -> None:
    """Leave it alone because a user-chosen luna block is a choice."""
    luna = {"type": "command", "command": claude_presets.luna_command()}

    assert not claude_presets.has_retired_hook({"hooks": {"Stop": [{"hooks": [luna]}]}})


def _managed_command(path: str) -> dict:
    return {"type": "command", "command": f"ADW_CLAUDE_MANAGED={claude_presets.MANAGED_MARKER} {path}"}


@pytest.mark.parametrize("path", [
    pytest.param("/old/hooks/claude_sonnet.sh", id="plain-path"),
    pytest.param("'/old root/hooks/claude_sonnet.sh'", id="path-the-writer-quoted"),
])
def test_a_managed_sonnet_command_is_retired(path: str) -> None:
    """Retired, because its script is gone and it ran headless Claude."""
    assert claude_presets.has_retired_hook({"hooks": {"Stop": [{"hooks": [_managed_command(path)]}]}})


def test_a_user_command_with_the_sonnet_script_name_is_not_retired() -> None:
    """Leave it alone because only the marker says ADW wrote it."""
    foreign = {"type": "command", "command": "/my/own/hooks/claude_sonnet.sh"}

    assert not claude_presets.has_retired_hook({"hooks": {"Stop": [{"hooks": [foreign]}]}})
