from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_cache


def _config(home: Path) -> Path:
    root = home / ".claude"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _seed_cache(home: Path, *revisions: str) -> Path:
    cache = _config(home).joinpath(*claude_cache.CACHE_PARTS)
    for revision in revisions:
        (cache / revision / "hooks").mkdir(parents=True)
        (cache / revision / "hooks" / "run.sh").write_text("stale", encoding="utf-8")
    return cache


def test_the_state_directory_is_never_a_target(tmp_path: Path) -> None:
    """Spare the collector because it holds the settings, the ledger, and the pinned Codex runtime."""
    _seed_cache(tmp_path, "aaaa1111")
    state = tmp_path / ".adw"
    (state / "state").mkdir(parents=True)
    (state / "config.json").write_text("{}", encoding="utf-8")

    list(claude_cache.nuke({}, tmp_path))

    assert (state / "config.json").read_text(encoding="utf-8") == "{}"
    assert (state / "state").is_dir()


def test_every_stale_revision_goes_in_one_pass(tmp_path: Path) -> None:
    """Clear them all because two cached revisions cannot say which one Claude Code loads."""
    cache = _seed_cache(tmp_path, "aaaa1111", "bbbb2222")
    assert len(claude_cache.installed_revisions({}, tmp_path)) == 2

    list(claude_cache.nuke({}, tmp_path))

    assert not cache.exists()
    assert claude_cache.installed_revisions({}, tmp_path) == ()


def test_a_stale_command_directory_goes_too(tmp_path: Path) -> None:
    """Remove it because a stale copy shadows the plugin and breaks the plugin root it resolves."""
    commands = _config(tmp_path).joinpath(*claude_cache.COMMAND_PARTS)
    commands.mkdir(parents=True)
    (commands / "update.md").write_text("stale", encoding="utf-8")

    removed = list(claude_cache.nuke({}, tmp_path))

    assert commands not in [path for path in removed if path.exists()]
    assert not commands.exists()


def test_nothing_installed_removes_nothing_and_raises_nothing(tmp_path: Path) -> None:
    """Stay quiet because a first-time install has no cache and must not read as a failure."""
    _config(tmp_path)

    assert list(claude_cache.nuke({}, tmp_path)) == []


def test_a_symlinked_cache_is_refused_rather_than_followed(tmp_path: Path) -> None:
    """Refuse the link because following it would delete whatever the attacker pointed it at."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    cache = _config(tmp_path).joinpath(*claude_cache.CACHE_PARTS)
    cache.parent.mkdir(parents=True)
    cache.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(claude_cache.NukeRefusal, match="symlink"):
        claude_cache.removable({}, tmp_path)

    assert elsewhere.is_dir()


def test_the_config_env_var_wins_when_it_points_at_a_directory(tmp_path: Path) -> None:
    """Honour the override because a user who moved their config still needs the stale cache cleared."""
    moved = tmp_path / "moved-config"
    moved.mkdir()
    _config(tmp_path)

    roots = claude_cache.config_roots({claude_cache.CONFIG_ENV: str(moved)}, tmp_path)

    assert roots[0] == moved


def test_an_unset_config_env_var_falls_back_without_raising(tmp_path: Path) -> None:
    """Skip a blank value because an exported but empty variable is the common shell accident."""
    _config(tmp_path)

    assert claude_cache.config_roots({claude_cache.CONFIG_ENV: "  "}, tmp_path) == (tmp_path / ".claude",)


def test_the_recorded_commit_names_what_claude_code_actually_loaded(tmp_path: Path) -> None:
    """Read the record because the directory names alone cannot say which revision is live."""
    root = _config(tmp_path)
    root.joinpath("plugins").mkdir(exist_ok=True)
    root.joinpath(*claude_cache.INSTALLED_LEAF).write_text(
        json.dumps({"plugins": {f"{claude_cache.PLUGIN}@{claude_cache.MARKETPLACE}": [
            {"gitCommitSha": "75f7111e0b54197f1a5d05cd4cb062b8c8383461"},
        ]}}),
        encoding="utf-8",
    )

    assert claude_cache.recorded_revision({}, tmp_path).startswith("75f7111e0b54")


def test_a_missing_record_reports_an_empty_revision_rather_than_raising(tmp_path: Path) -> None:
    """Answer empty because a first-time install has no record and must not crash the updater."""
    _config(tmp_path)

    assert claude_cache.recorded_revision({}, tmp_path) == ""


def test_a_target_outside_the_config_root_is_refused(tmp_path: Path) -> None:
    """Check containment because one wrong variable moves the whole target out of the config tree."""
    with pytest.raises(claude_cache.NukeRefusal, match="not the ADW cache"):
        claude_cache._guard(tmp_path / "somewhere", tmp_path, claude_cache.CACHE_PARTS)


def test_removing_the_pinned_root_is_reported_rather_than_done_in_silence(tmp_path: Path) -> None:
    """Warn the caller because Claude Code resolves the plugin root once and a wipe silences every hook."""
    cache = _seed_cache(tmp_path, "aaaa1111")
    live = {claude_cache.PLUGIN_ROOT_ENV: str(cache / "aaaa1111")}

    assert claude_cache.pins_live_session(cache, live) is True


def test_a_cache_the_session_never_loaded_reports_no_collision(tmp_path: Path) -> None:
    """Stay quiet because a warning on every run teaches the reader to skip the one that matters."""
    cache = _seed_cache(tmp_path, "aaaa1111")
    elsewhere = {claude_cache.PLUGIN_ROOT_ENV: str(tmp_path / "other-plugin" / "bbbb2222")}

    assert claude_cache.pins_live_session(cache, elsewhere) is False


def test_an_unset_plugin_root_reports_no_collision(tmp_path: Path) -> None:
    """Answer false because an installer run outside a hook has no session to silence."""
    cache = _seed_cache(tmp_path, "aaaa1111")

    assert claude_cache.pins_live_session(cache, {}) is False
