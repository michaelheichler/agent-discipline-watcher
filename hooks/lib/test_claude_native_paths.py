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
        "luna", _untouched, _never_retired, settings_file=settings, preset_file=preset,
    )

    assert chosen == "luna"
    assert claude_native.read_preset(preset, settings_path=settings) == "luna"
    assert "claude_luna.sh" in json.dumps(json.loads(settings.read_text(encoding="utf-8")))


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

    chosen = claude_native.ensure_managed_block("luna", marked, _never_retired, settings_file=settings, preset_file=preset)

    assert chosen is None
    assert json.loads(settings.read_text(encoding="utf-8"))["repointed"] is True
    assert claude_native.read_preset(preset, settings_path=settings) == "luna"


@pytest.mark.parametrize("explicit", [pytest.param(True, id="explicit-settings"), pytest.param(False, id="config-profile")])
def test_settings_overrides_keep_explicit_file_precedence_before_creation(tmp_path, monkeypatch, explicit) -> None:
    profile = tmp_path / "custom"
    settings = tmp_path / "selected.json"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(profile))
    monkeypatch.delenv("ADW_CLAUDE_SETTINGS", raising=False)
    configure_explicit_settings(monkeypatch, settings, explicit)

    result = claude_native.settings_path()

    assert result == (settings if explicit else profile / "settings.json")
    assert not profile.exists()


def configure_explicit_settings(monkeypatch, settings, enabled) -> None:
    if enabled:
        monkeypatch.setenv("ADW_CLAUDE_SETTINGS", str(settings))
