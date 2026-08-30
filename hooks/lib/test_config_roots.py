from __future__ import annotations

from pathlib import Path

import pytest

from lib import collector, config_roots, host


def test_three_hosts_read_their_own_directory_then_the_shared_one(tmp_path: Path) -> None:
    """Order host before shared because a per-host value must win over a machine default."""
    env = {config_roots.STATE_ENV: str(tmp_path)}

    for name in (host.CLAUDE, host.CODEX, host.OMP):
        assert config_roots.roots_for(name, env) == (tmp_path / "hosts" / name, tmp_path)


def test_cowork_reads_the_shipped_copy_and_never_the_home_directory(tmp_path: Path) -> None:
    """Skip the home directory because the Cowork VM never mounts it."""
    env = {config_roots.PLUGIN_ROOT_ENV: str(tmp_path), config_roots.STATE_ENV: "/should/not/appear"}

    resolved = config_roots.roots_for(host.COWORK, env)

    assert resolved == (tmp_path / config_roots.DEFAULTS_LEAF,)
    assert all("should/not/appear" not in str(path) for path in resolved)


def test_cowork_without_a_plugin_root_yields_no_root(tmp_path: Path) -> None:
    """Return nothing because a guessed path would load a policy nobody installed."""
    assert config_roots.roots_for(host.COWORK, {}) == ()


def test_an_undeclared_host_raises_rather_than_guessing() -> None:
    """Refuse a default because a wrong root would run a policy the user never chose."""
    with pytest.raises(ValueError):
        config_roots.roots_for("some-future-host", {})


def test_every_supported_host_declares_its_roots(tmp_path: Path) -> None:
    """Cover the roster because a runtime with no declared root cannot load anything."""
    env = {config_roots.STATE_ENV: str(tmp_path), config_roots.PLUGIN_ROOT_ENV: str(tmp_path)}

    for name in host.SUPPORTED:
        assert config_roots.roots_for(name, env) is not None


def test_the_collector_answers_for_a_host_with_no_tree_on_disk(tmp_path: Path) -> None:
    """Prove the pair works because a fresh install has neither directory yet."""
    env = {config_roots.STATE_ENV: str(tmp_path / "absent"), host.CLAUDE_ENV: "1"}

    loaded = collector.load(config_roots.roots(env))

    assert loaded.values == {}
    assert loaded.sources == ()
