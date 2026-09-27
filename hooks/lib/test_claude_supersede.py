"""Split out because the host cannot switch off one plugin hook."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from lib import claude_native, claude_presets


def test_the_haiku_settings_block_supersedes_the_plugin(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"

    claude_native.set_preset("haiku", settings_path=settings, preset_path=tmp_path / "preset")

    assert claude_presets.plugin_superseded(settings)


def test_unreadable_settings_leave_the_plugin_reviewer_running(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{not json", encoding="utf-8")

    assert not claude_presets.plugin_superseded(settings)
    assert not claude_presets.plugin_superseded(tmp_path / "missing.json")


def test_the_journal_helper_reports_a_superseding_preset(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    claude_native.set_preset("mixed", settings_path=settings, preset_path=tmp_path / "preset")
    reader = Path(__file__).parents[1] / "read_claude_journal.sh"

    result = subprocess.run(
        [str(reader), claude_presets.SUPERSEDED_FLAG],
        env={**os.environ, "HOME": str(tmp_path), "ADW_CLAUDE_SETTINGS": str(settings)},
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "true"
