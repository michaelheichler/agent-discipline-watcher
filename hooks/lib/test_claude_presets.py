from __future__ import annotations

import pytest

from lib import claude_presets


def test_the_roster_is_exactly_the_four_the_user_chose() -> None:
    """Pin the roster because a sonnet-everywhere preset was rejected and must not return quietly."""
    assert claude_presets.PRESETS == ("haiku", "mixed", "luna", "luna-native")


def test_a_sonnet_everywhere_preset_is_refused() -> None:
    """Refuse it by name because it was a real preset and an old settings file may still ask for it."""
    with pytest.raises(ValueError, match="haiku, mixed, luna, or luna-native"):
        claude_presets.validate_preset("sonnet")


def test_a_stored_sonnet_preset_reads_as_the_preset_that_replaced_it(tmp_path) -> None:
    """Map it because a dropped name reads as no preset, and status would then report haiku while Sonnet still runs."""
    from lib import claude_native

    stored = tmp_path / "preset"
    stored.write_text("sonnet\n", encoding="utf-8")

    assert claude_native._read_preset_unlocked(stored) == "mixed"


def test_mixed_spends_the_cheaper_model_on_the_more_frequent_role() -> None:
    """Split the roles because a comment check runs per write while a document check runs per turn."""
    assert claude_presets.model_for("mixed", "comment") == "haiku"
    assert claude_presets.model_for("mixed", "document") == "sonnet"


def test_haiku_runs_one_model_for_both_roles() -> None:
    """Keep it uniform because this preset exists to hold cost flat."""
    assert claude_presets.model_for("haiku", "comment") == "haiku"
    assert claude_presets.model_for("haiku", "document") == "haiku"


def test_luna_native_names_the_model_the_harness_injects() -> None:
    """Name it because LeverFrame puts Luna in the Claude model list and an agent hook can then ask for it."""
    assert claude_presets.model_for("luna-native", "comment") == claude_presets.LUNA_NATIVE_MODEL


def test_luna_refuses_a_native_model_because_it_runs_a_command() -> None:
    """Separate the two because the SDK preset reaches Luna through a handler rather than the host."""
    with pytest.raises(ValueError, match="command handlers"):
        claude_presets.model_for("luna", "comment")


@pytest.mark.parametrize("preset", ("haiku", "mixed", "luna-native"))
def test_every_agent_preset_registers_a_reviewer_on_both_events(preset: str) -> None:
    """Cover both because a write check alone leaves the finished turn unreviewed."""
    generated = claude_presets.generated_hooks(preset)

    assert generated["PostToolUse"][0]["hooks"][0]["type"] == "agent"
    assert generated["Stop"][0]["hooks"][0]["type"] == "agent"


def test_the_luna_preset_registers_a_command_on_both_events() -> None:
    """Register a command because python reaches Luna through the SDK rather than through the host."""
    generated = claude_presets.generated_hooks("luna")

    assert generated["PostToolUse"][0]["hooks"][0]["type"] == "command"
    assert generated["Stop"][0]["hooks"][0]["type"] == "command"


@pytest.mark.parametrize("preset", claude_presets.PRESETS)
def test_no_preset_registers_a_handler_on_pre_tool_use(preset: str) -> None:
    """Stay off PreToolUse because a non-conforming reply there denies the tool call, reproduced in f9da7d5."""
    assert "PreToolUse" not in claude_presets.generated_hooks(preset)


@pytest.mark.parametrize("preset", claude_presets.PRESETS)
def test_every_generated_handler_carries_the_managed_marker(preset: str) -> None:
    """Mark them because a second merge duplicates any entry the merger cannot recognise as ours."""
    generated = claude_presets.generated_hooks(preset)
    entries = [group["hooks"][0] for groups in generated.values() for group in groups]

    for entry in entries:
        carrier = entry.get("prompt") or entry.get("command")
        assert claude_presets.MANAGED_MARKER in carrier
