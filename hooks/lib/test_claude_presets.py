from __future__ import annotations

import pytest

from lib import claude_native, claude_presets


@pytest.mark.parametrize("retired", ("haiku", "luna-native", "sonnet"))
def test_a_retired_preset_is_refused(retired: str) -> None:
    """Refuse it by name because an old settings file may still ask for it."""
    with pytest.raises(ValueError, match="mixed or luna"):
        claude_presets.validate_preset(retired)


@pytest.mark.parametrize("retired", ("haiku", "luna-native", "sonnet"))
def test_a_stored_retired_preset_reads_as_the_preset_that_replaced_it(tmp_path, retired: str) -> None:
    """Map it because a dropped name reads as no preset, and status would then report a default while a retired reviewer runs."""
    stored = tmp_path / "preset"
    stored.write_text(f"{retired}\n", encoding="utf-8")

    assert claude_native.read_preset(stored, settings_path=tmp_path / "settings.json") == "mixed"


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


def test_mixed_registers_one_sonnet_command_on_stop_only() -> None:
    """Stop only, because the journal already holds each write."""
    generated = claude_presets.generated_hooks("mixed")

    assert set(generated) == {"Stop"}
    assert len(generated["Stop"]) == 1
    assert generated["Stop"][0]["hooks"][0]["command"] == claude_presets.sonnet_command()


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
    assert claude_presets.has_retired_agent_hook(settings)
    assert claude_presets.without_managed(settings)["hooks"] == {}


def test_an_agent_hook_without_the_marker_is_not_retired() -> None:
    """Leave it alone because it belongs to the user."""
    foreign = {"type": "agent", "model": "haiku", "prompt": "someone else's reviewer"}

    assert not claude_presets.has_retired_agent_hook({"hooks": {"Stop": [{"hooks": [foreign]}]}})


def test_a_luna_command_block_is_not_retired() -> None:
    """Leave it alone because a user-chosen luna block is a choice."""
    luna = {"type": "command", "command": claude_presets.luna_command()}

    assert not claude_presets.has_retired_agent_hook({"hooks": {"Stop": [{"hooks": [luna]}]}})
