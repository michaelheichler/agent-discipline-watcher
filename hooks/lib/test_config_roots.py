"""Because policy paths cannot redirect protected data, physical roots stay separate from overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import collector, config_roots, host


@pytest.mark.parametrize("name", (host.CLAUDE, host.CODEX, host.OMP))
def test_three_hosts_read_their_own_directory_then_the_shared_one(tmp_path: Path, name: str) -> None:
    """Order host before shared because a per-host value must win over a machine default."""
    env = {config_roots.STATE_ENV: str(tmp_path)}

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


@pytest.mark.parametrize("name", host.SUPPORTED)
def test_every_supported_host_declares_its_roots(tmp_path: Path, name: str) -> None:
    """Cover the roster because a runtime with no declared root cannot load anything."""
    env = {config_roots.STATE_ENV: str(tmp_path), config_roots.PLUGIN_ROOT_ENV: str(tmp_path)}

    assert config_roots.roots_for(name, env) is not None


def test_the_collector_answers_for_a_host_with_no_tree_on_disk(tmp_path: Path) -> None:
    """Prove the pair works because a fresh install has neither directory yet."""
    env = {config_roots.STATE_ENV: str(tmp_path / "absent"), host.CLAUDE_ENV: "1"}

    loaded = collector.load(config_roots.roots(env))

    assert loaded.values == {}
    assert loaded.sources == ()


@pytest.mark.parametrize("home_type", [str, Path], ids=["string", "path"])
def test_explicit_home_is_independent_of_the_ambient_home(
    tmp_path: Path, monkeypatch, home_type,
) -> None:
    home = tmp_path / "injected"
    monkeypatch.setenv("HOME", str(tmp_path / "ambient"))

    result = config_roots.home_root(home_type(home))

    assert result == home


def test_explicit_home_expands_a_user_relative_path_under_the_isolated_home(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    result = config_roots.home_root("~/injected")

    assert result == tmp_path / "injected"


def test_physical_data_root_cannot_be_redirected_by_a_state_override(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "physical-home"
    override = tmp_path / "policy-state"
    monkeypatch.setenv(config_roots.STATE_ENV, str(override))

    result = config_roots.data_root(home)

    assert result.is_relative_to(home)
    assert not result.is_relative_to(override)


@pytest.mark.parametrize("value", ["", " ", "\t\n"], ids=["empty", "space", "whitespace"])
def test_blank_explicit_state_override_uses_the_physical_root_not_the_ambient_override(
    tmp_path: Path, monkeypatch, value: str,
) -> None:
    home = tmp_path / "physical-home"
    monkeypatch.setenv(config_roots.STATE_ENV, str(tmp_path / "ambient-override"))

    result = config_roots.state_root({config_roots.STATE_ENV: value}, home=home)

    assert result == config_roots.data_root(home)


def test_explicit_state_environment_does_not_read_an_ambient_override(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "physical-home"
    monkeypatch.setenv(config_roots.STATE_ENV, str(tmp_path / "ambient-override"))

    result = config_roots.state_root({}, home=home)

    assert result == config_roots.data_root(home)


def test_configured_state_root_uses_the_trimmed_override_not_the_physical_root(tmp_path: Path) -> None:
    home = tmp_path / "physical-home"
    override = tmp_path / "configured-state"

    result = config_roots.state_root({config_roots.STATE_ENV: f" {override} \n"}, home=home)

    assert result == override
    assert not result.is_relative_to(home)


def test_implicit_state_environment_reads_the_configured_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "configured-state"
    monkeypatch.setenv(config_roots.STATE_ENV, str(override))

    result = config_roots.state_root(home=tmp_path / "physical-home")

    assert result == override


def test_user_relative_state_override_expands_only_within_the_isolated_home(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    result = config_roots.state_root({config_roots.STATE_ENV: "~/configured-state"}, home=tmp_path)

    assert result == tmp_path / "configured-state"


def test_installation_root_cannot_follow_a_state_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADW_STATE_ROOT", str(tmp_path / "other-state"))

    assert config_roots.install_root(tmp_path) == tmp_path / ".adw" / "install" / "agent-discipline-watcher"


@pytest.mark.parametrize("token, suffix", [
    pytest.param("~", "", id="tilde"),
    pytest.param("~/x", "x", id="tilde-child"),
    pytest.param("$HOME", "", id="home"),
    pytest.param("$HOME/x", "x", id="home-child"),
    pytest.param("${HOME}", "", id="braced-home"),
    pytest.param("${HOME}/x", "x", id="braced-home-child"),
])
def test_home_tokens_expand_only_against_the_injected_home(tmp_path, token, suffix) -> None:
    assert config_roots.home_relative(token, tmp_path) == tmp_path / suffix


@pytest.mark.parametrize("token", [
    pytest.param("~other/x", id="other-user"),
    pytest.param("$HOMEother/x", id="variable-prefix"),
])
def test_home_token_prefixes_do_not_expand_as_home(tmp_path, token) -> None:
    assert config_roots.home_relative(token, tmp_path) is None
