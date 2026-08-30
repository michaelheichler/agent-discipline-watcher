from __future__ import annotations

import json
from pathlib import Path

from lib import claude_native, judge_status

AGENT = {"type": "agent", "model": "haiku", "timeout": 30, "prompt": "adw-managed-hook-v1\nreview"}
COMMAND = {"type": "command", "command": "run.sh Stop", "timeout": 10}


def _manifest(path: Path, *groups: dict) -> Path:
    path.write_text(json.dumps({"hooks": {"PostToolUse": list(groups)}}), encoding="utf-8")
    return path


def test_the_shipped_manifest_carries_its_reviewers(tmp_path: Path) -> None:
    """Count the manifest because installing the plugin is the whole setup for a default user."""
    manifest = _manifest(tmp_path / "hooks.json", {"hooks": [COMMAND]}, {"hooks": [AGENT]})

    assert judge_status.plugin_reviewers(manifest) == 1


def test_a_manifest_without_an_agent_reports_zero(tmp_path: Path) -> None:
    """Report zero because d606abc shipped exactly this shape and the gate looked healthy."""
    manifest = _manifest(tmp_path / "hooks.json", {"hooks": [COMMAND]})

    assert judge_status.plugin_reviewers(manifest) == 0


def test_a_missing_manifest_reports_zero_rather_than_raising(tmp_path: Path) -> None:
    """Survive the absence because a status read must never crash the command that explains the gate."""
    assert judge_status.plugin_reviewers(tmp_path / "absent.json") == 0


def test_a_machine_with_no_install_reports_zero(tmp_path: Path, monkeypatch) -> None:
    """Read the install because this checkout carries two reviewers whether or not anyone installed it."""
    monkeypatch.delenv(judge_status.PLUGIN_ROOT_ENV, raising=False)
    monkeypatch.setenv(judge_status.CONFIG_ENV, str(tmp_path / "empty-config"))

    assert judge_status.plugin_reviewers() == 0


def test_the_pinned_plugin_root_wins_over_the_cache_scan(tmp_path: Path, monkeypatch) -> None:
    """Prefer the pinned root because that is the copy whose hooks the running session loaded."""
    root = tmp_path / "pinned"
    (root / "hooks").mkdir(parents=True)
    _manifest(root / "hooks" / "hooks.json", {"hooks": [AGENT]})
    monkeypatch.setenv(judge_status.PLUGIN_ROOT_ENV, str(root))

    assert judge_status.plugin_reviewers() == 1


def test_a_pinned_root_without_a_manifest_reports_zero(tmp_path: Path, monkeypatch) -> None:
    """Answer zero because a wiped cache leaves the variable pointing at a directory that is gone."""
    monkeypatch.setenv(judge_status.PLUGIN_ROOT_ENV, str(tmp_path / "gone"))

    assert judge_status.plugin_reviewers() == 0


def test_a_corrupt_manifest_reports_zero_rather_than_raising(tmp_path: Path) -> None:
    """Survive bad JSON because a half-written settings file must not take the status command with it."""
    broken = tmp_path / "hooks.json"
    broken.write_text("{not json", encoding="utf-8")

    assert judge_status.plugin_reviewers(broken) == 0


def test_settings_reviewers_count_only_the_managed_entries(tmp_path: Path) -> None:
    """Count ours alone because deleting somebody else's hook is not this command's business."""
    settings = tmp_path / "settings.json"
    foreign = {"type": "agent", "model": "haiku", "prompt": "someone else's reviewer"}
    settings.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [AGENT, foreign, COMMAND]}]}}), encoding="utf-8"
    )

    counted = judge_status.settings_reviewers(settings, claude_native._is_managed_hook)

    assert counted == 1


def test_an_unwired_gate_says_so_instead_of_naming_a_preset() -> None:
    """Say it plainly because a preset naming a model that nothing runs still reads as working."""
    described = judge_status.describe("haiku", stored=False, reviewers=0)

    assert described["judging"].startswith("no reviewer is registered")
    assert described["source"] == "default"


def test_a_wired_gate_reports_the_count_it_found() -> None:
    """Report the number because one reviewer and two reviewers are different gates."""
    described = judge_status.describe("mixed", stored=True, reviewers=2)

    assert described == {
        "preset": "mixed", "source": "stored", "reviewers": "2", "judging": "yes",
    }
