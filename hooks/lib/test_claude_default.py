"""Split from the session-start tests, because an upgrade from the Sonnet preset rewrites a settings file the user also owns."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_default, claude_native, claude_presets

USER_STOP = {"type": "command", "command": "keep-this-stop"}
USER_POST = {"type": "command", "command": "keep-this-post"}
USER_POST_GROUP = {"matcher": "Write", "hooks": [USER_POST]}
PLAIN_HANDLER = "/old/hooks/claude_sonnet.sh"


def _sonnet_handler(path: str) -> dict:
    return {"type": "command", "command": f"ADW_CLAUDE_MANAGED={claude_presets.MANAGED_MARKER} {path}", "timeout": 120}


def _upgraded_files(tmp_path: Path, handler: str) -> tuple[Path, Path]:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    settings.write_text(json.dumps({
        "model": "keep-this-model",
        "hooks": {
            "PostToolUse": [USER_POST_GROUP],
            "Stop": [{"hooks": [_sonnet_handler(handler)]}, {"hooks": [USER_STOP]}],
        },
    }), encoding="utf-8")
    preset.write_text("mixed\n", encoding="utf-8")
    return settings, preset


def _commands(configured: dict, lifecycle: str) -> list[str]:
    return sorted(hook["command"] for group in configured["hooks"][lifecycle] for hook in group["hooks"])


@pytest.mark.parametrize("handler", [
    pytest.param(PLAIN_HANDLER, id="plain-path"),
    pytest.param("'/old root/hooks/claude_sonnet.sh'", id="path-the-writer-quoted"),
])
def test_a_sonnet_block_with_a_stored_mixed_preset_becomes_exactly_the_luna_block(tmp_path: Path, handler: str) -> None:
    settings, preset = _upgraded_files(tmp_path, handler)

    claude_default.ensure_default_block(settings, preset)

    configured = json.loads(settings.read_text(encoding="utf-8"))
    assert claude_presets.managed_hooks(configured) == claude_presets.managed_hooks({"hooks": claude_presets.generated_hooks("luna")})


def test_the_sonnet_migration_keeps_every_user_owned_hook_and_setting(tmp_path: Path) -> None:
    settings, preset = _upgraded_files(tmp_path, PLAIN_HANDLER)

    claude_default.ensure_default_block(settings, preset)

    configured = json.loads(settings.read_text(encoding="utf-8"))
    luna = claude_presets.luna_command()
    assert _commands(configured, "Stop") == sorted([luna, USER_STOP["command"]])
    assert _commands(configured, "PostToolUse") == sorted([luna, USER_POST["command"]])
    assert USER_POST_GROUP in configured["hooks"]["PostToolUse"]
    assert configured["model"] == "keep-this-model"


def test_the_sonnet_migration_stores_luna_in_place_of_mixed(tmp_path: Path) -> None:
    settings, preset = _upgraded_files(tmp_path, PLAIN_HANDLER)

    claude_default.ensure_default_block(settings, preset)

    assert preset.read_text(encoding="utf-8") == "luna\n"


def test_a_second_session_after_the_sonnet_migration_writes_nothing(tmp_path: Path) -> None:
    settings, preset = _upgraded_files(tmp_path, PLAIN_HANDLER)
    claude_default.ensure_default_block(settings, preset)
    once = settings.read_text(encoding="utf-8")

    claude_default.ensure_default_block(settings, preset)

    assert settings.read_text(encoding="utf-8") == once


def test_a_user_edited_luna_block_survives_the_migration_path(tmp_path: Path) -> None:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    edited = json.loads(settings.read_text(encoding="utf-8"))
    edited["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 45
    settings.write_text(json.dumps(edited), encoding="utf-8")

    claude_default.ensure_default_block(settings, preset)

    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 45
