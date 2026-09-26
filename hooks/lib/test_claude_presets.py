from __future__ import annotations

import pytest

from lib import claude_presets
from lib.judge_contracts import DOCUMENT_RUBRIC, PATTERN_RUBRIC


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
    assert claude_presets.model_for("mixed", "comment") == "claude-haiku-4-5-20251001"
    assert claude_presets.model_for("mixed", "document") == "claude-sonnet-4-6"


def test_haiku_runs_one_model_for_both_roles() -> None:
    """Keep it uniform because this preset exists to hold cost flat."""
    assert claude_presets.model_for("haiku", "comment") == "claude-haiku-4-5-20251001"
    assert claude_presets.model_for("haiku", "document") == "claude-haiku-4-5-20251001"


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
    generated = claude_presets.generated_hooks(preset) or claude_presets.shipped_hooks()

    for event in ("PostToolUse", "Stop"):
        entry = generated[event][0]["hooks"][0]
        assert entry["type"] == "agent"
        assert "StructuredOutput" in entry["prompt"]
        assert "exactly once" in entry["prompt"]
        assert "plain text" in entry["prompt"]
        assert "JSON:" not in entry["prompt"]
    stop_prompt = generated["Stop"][0]["hooks"][0]["prompt"]
    assert "skip every remaining step" in stop_prompt
    assert stop_prompt.index("Batch all") < stop_prompt.index("OUTPUT CONTRACT")


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


def test_the_haiku_preset_writes_no_settings_entry_because_the_plugin_ships_it() -> None:
    """Write nothing because a settings copy of the shipped reviewer runs a second Haiku agent."""
    assert not claude_presets.generated_hooks("haiku")


@pytest.mark.parametrize("preset", ("mixed", "luna", "luna-native"))
def test_a_written_preset_supersedes_the_shipped_reviewer(preset: str) -> None:
    """Yield the plugin entries because the host cannot switch off one plugin hook."""
    settings = {"hooks": claude_presets.generated_hooks(preset)}

    assert claude_presets.supersedes_plugin(settings)


def test_a_legacy_copy_of_the_shipped_reviewer_does_not_supersede_itself() -> None:
    """Keep it running because an installer copy of the plugin entry is the only reviewer there."""
    legacy = {"hooks": claude_presets.shipped_hooks()}

    assert not claude_presets.supersedes_plugin(legacy)
    assert not claude_presets.supersedes_plugin({})


def test_every_shipped_reviewer_checks_for_a_superseding_preset_first() -> None:
    """Check first because a skipped reviewer must spend no review work."""
    generated = claude_presets.shipped_hooks()

    for event in ("PostToolUse", "Stop"):
        prompt = generated[event][0]["hooks"][0]["prompt"]
        assert claude_presets.SUPERSEDED_FLAG in prompt
        assert prompt.index(claude_presets.SUPERSEDED_FLAG) < prompt.index("OUTPUT CONTRACT")


@pytest.mark.parametrize("preset", ("haiku", "mixed", "luna-native"))
def test_every_stop_reviewer_judges_pattern_rows_against_their_examples(preset: str) -> None:
    """Pinned, because a rubric-free judge drifted to taste."""
    prompt = claude_presets.stop_prompt(preset)

    assert PATTERN_RUBRIC in prompt
    assert "rule entry" in prompt
    assert "four violating and four clean" in prompt
    assert prompt.index(PATTERN_RUBRIC) < prompt.index("OUTPUT CONTRACT")


@pytest.mark.parametrize("preset", ("haiku", "luna-native"))
def test_only_mixed_asks_for_document_rows(preset: str) -> None:
    """Opt in, because a whole document costs the most tokens."""
    prompt = claude_presets.stop_prompt(preset)

    assert claude_presets.DOCUMENTS_FLAG not in prompt
    assert DOCUMENT_RUBRIC not in prompt


def test_mixed_judges_document_rows_as_whole_documents() -> None:
    prompt = claude_presets.stop_prompt("mixed")

    assert f"{claude_presets.DOCUMENTS_FLAG} " in prompt
    assert DOCUMENT_RUBRIC in prompt


@pytest.mark.parametrize("preset", ("haiku", "mixed", "luna-native"))
def test_no_stop_reviewer_opens_a_file(preset: str) -> None:
    """Rows carry the text, because a file read costs the whole file."""
    prompt = claude_presets.stop_prompt(preset)

    assert "Never open a file" in prompt
    assert "Read the named path" not in prompt
