from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_native, claude_journal


def test_mixed_profile_batches_comment_and_document_roles() -> None:
    generated = claude_native.generated_hooks("mixed")

    assert set(generated) == {"PostToolUse", "Stop"}
    post = generated["PostToolUse"][0]
    stop = generated["Stop"][0]
    assert post["matcher"] == "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
    assert post["hooks"][0]["type"] == "agent"
    assert post["hooks"][0]["model"] == "haiku"
    assert stop["hooks"][0]["type"] == "agent"
    assert stop["hooks"][0]["model"] == "sonnet"
    assert "batch" in stop["hooks"][0]["prompt"].lower()


def test_native_agents_never_register_a_pretool_hook() -> None:
    for preset in claude_native.PRESETS:
        assert "PreToolUse" not in claude_native.generated_hooks(preset)


@pytest.mark.parametrize("preset", ("mixed", "luna", "haiku", "sonnet"))
def test_preset_switch_is_idempotent_and_preserves_unrelated_settings(tmp_path: Path, preset: str) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "model": "claude-opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]},
    }), encoding="utf-8")

    first = claude_native.set_preset(preset, settings_path=settings, preset_path=tmp_path / "preset")
    once = settings.read_text(encoding="utf-8")
    second = claude_native.set_preset(preset, settings_path=settings, preset_path=tmp_path / "preset")

    assert first == second == preset
    assert settings.read_text(encoding="utf-8") == once
    merged = json.loads(once)
    assert merged["model"] == "claude-opus"
    assert {row["hooks"][0]["command"] for row in merged["hooks"]["Stop"] if row["hooks"][0]["type"] == "command"} == {"other"}


def test_preset_selection_uses_only_exact_remote_signal_or_explicit_haiku(tmp_path: Path) -> None:
    assert claude_native.default_preset({}, preset_path=tmp_path / "missing") == "mixed"
    assert claude_native.default_preset({"CLAUDE_CODE_REMOTE": "true"}, preset_path=tmp_path / "missing") == "haiku"
    assert claude_native.default_preset({"CLAUDE_CODE_REMOTE": "TRUE"}, preset_path=tmp_path / "missing") == "mixed"
    assert claude_native.default_preset({"ADW_CLAUDE_HAIKU_ONLY": "1"}, preset_path=tmp_path / "missing") == "haiku"
    assert claude_native.default_preset({"TERM_PROGRAM": "Claude"}, preset_path=tmp_path / "missing") == "mixed"


def test_candidate_journal_deduplicates_final_content_hash_and_excludes_unrelated_files(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    unrelated = tmp_path / "b.py"
    unrelated.write_text("value = 2\n", encoding="utf-8")

    first = claude_journal.record_edit("session", "turn-1", "tool-1", source, state_root=tmp_path / "state")
    second = claude_journal.record_edit("session", "turn-1", "tool-2", source, state_root=tmp_path / "state")

    assert first
    assert second == []
    rows = claude_journal.read("session", state_root=tmp_path / "state")
    assert len(rows) == 1
    assert rows[0]["path"] == str(source)
    assert rows[0]["content_hash"]
    assert str(unrelated) not in json.dumps(rows)


def test_native_prompts_fail_open_for_empty_input_and_check_stop_loop() -> None:
    prompt = claude_native.comment_prompt("mixed") + claude_native.stop_prompt("mixed")
    assert "malformed" in prompt.lower()
    assert '"ok": true' in prompt
    assert "read-only" in prompt
    assert "stop_hook_active" in prompt


def test_luna_failure_switches_to_role_fallback_once(tmp_path: Path) -> None:
    claude_native.set_preset("luna", settings_path=tmp_path / "settings.json", preset_path=tmp_path / "preset")

    result = claude_native.fallback_after_luna_failure(
        "comment", "subscription unavailable", settings_path=tmp_path / "settings.json", preset_path=tmp_path / "preset",
    )

    assert result["preset"] == "haiku"
    assert "subscription unavailable" in result["message"]
    assert claude_native.read_preset(tmp_path / "preset") == "haiku"
