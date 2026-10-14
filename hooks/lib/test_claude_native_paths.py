"""Split from the native preset tests, because default path resolution has its own contract."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_native


def _untouched(settings: dict) -> dict:
    return settings


def _never_retired(_settings: dict) -> bool:
    return False


def test_an_empty_settings_file_gets_the_default_block(tmp_path: Path) -> None:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"

    chosen = claude_native.ensure_managed_block(
        "mixed", _untouched, _never_retired, settings_file=settings, preset_file=preset,
    )

    assert chosen == "mixed"
    assert claude_native.read_preset(preset, settings_path=settings) == "mixed"
    assert "claude_sonnet.sh" in json.dumps(json.loads(settings.read_text(encoding="utf-8")))


def test_without_paths_the_environment_names_both_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, preset = tmp_path / "env-settings.json", tmp_path / "env-preset"
    monkeypatch.setenv(claude_native.SETTINGS_ENV, str(settings))
    monkeypatch.setenv(claude_native.PRESET_FILE_ENV, str(preset))

    claude_native.ensure_managed_block("luna", _untouched, _never_retired)

    assert preset.read_text(encoding="utf-8").strip() == "luna"
    assert claude_native.status()["settings"] == str(settings)


def test_a_managed_block_is_repointed_not_replaced(tmp_path: Path) -> None:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)

    def marked(current: dict) -> dict:
        return {**current, "repointed": True}

    chosen = claude_native.ensure_managed_block("mixed", marked, _never_retired, settings_file=settings, preset_file=preset)

    assert chosen is None
    assert json.loads(settings.read_text(encoding="utf-8"))["repointed"] is True
    assert claude_native.read_preset(preset, settings_path=settings) == "luna"
