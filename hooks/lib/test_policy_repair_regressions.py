"""Keep policy validation and path identity covered because aliases must not release gates."""
from __future__ import annotations

from contextlib import nullcontext
import fcntl
import json
import os

import pytest

from lib import config, configure_store, protected


@pytest.mark.parametrize("relative,expected", [
    pytest.param("home/.adw/state.json", "state_mutation", id="state"),
    pytest.param("home/.claude/plugins/agent-discipline-watcher/hooks/protected.py",
                 "watcher_install_surface", id="install"),
    pytest.param("project/.agent-discipline.json", "config_seal", id="config"),
])
def test_a_hard_link_cannot_hide_a_protected_owner(tmp_path, relative, expected) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    alias = tmp_path / "project" / "alias"
    alias.parent.mkdir(exist_ok=True)
    alias.hardlink_to(target)

    rows = protected.path_findings(str(alias), home=tmp_path / "home",
                                   content='{"tests":"allow"}')

    assert expected in {row["rule"] for row in rows}


@pytest.mark.parametrize("name,body", [
    pytest.param("plain.txt", "Keep the note.", id="ordinary"),
    pytest.param(".agent-discipline.json", '{"tests":"deny"}', id="unchanged-config"),
])
def test_a_benign_hard_link_write_stays_editable(tmp_path, name, body) -> None:
    target = tmp_path / name
    target.write_text(body, encoding="utf-8")
    alias = tmp_path / "alias"
    alias.hardlink_to(target)

    rows = protected.path_findings(str(alias), home=tmp_path / "home", content=body)

    assert rows == []


@pytest.mark.parametrize("route,expected", [
    pytest.param("alias", {"watcher_install_surface"}, id="hidden-install"),
    pytest.param("source", set(), id="canonical-checkout"),
])
def test_live_install_identity_preserves_the_canonical_checkout(tmp_path, route, expected) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "checkout"
    source = checkout / "hooks" / "protected.py"
    source.parent.mkdir(parents=True)
    source.write_text("Keep the note.", encoding="utf-8")
    install = home / ".claude/plugins/agent-discipline-watcher"
    install.parent.mkdir(parents=True)
    install.symlink_to(checkout, target_is_directory=True)
    (checkout / "cycle").symlink_to(checkout, target_is_directory=True)
    alias = tmp_path / "alias"
    alias.hardlink_to(source)
    paths = {"alias": alias, "source": source}

    rows = protected.path_findings(str(paths[route]), home=home, content="Changed note.")

    assert {row["rule"] for row in rows} == expected


@pytest.mark.parametrize("container", ["top", "checks"])
@pytest.mark.parametrize("value,expected", [
    pytest.param("false", "enforce", id="string"),
    pytest.param(1, "enforce", id="integer"),
    pytest.param(False, "enforce", id="boolean-false"),
    pytest.param(True, "off", id="boolean-true"),
])
def test_only_boolean_project_kill_switches_disable_a_family(
        tmp_path, capsys, container, value, expected) -> None:
    settings = {"kill_switches": {"clean_code": value}}
    payload = {"top": settings, "checks": {"checks": settings}}[container]
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(payload), encoding="utf-8")

    effective = config.effective_config(cwd=tmp_path)

    assert config.gate_state("clean_code", effective) == expected
    assert bool(capsys.readouterr().err) == (type(value) is not bool)


@pytest.mark.parametrize("value", [
    pytest.param("false", id="string"), pytest.param(1, id="integer"),
])
def test_caller_kill_switches_cannot_use_truthiness_to_disable_a_family(value) -> None:
    assert config.gate_state("clean_code", {"kill_switches": {"clean_code": value}}) == "enforce"


MALFORMED = [
    pytest.param({"gates": {"clean_code": False}}, id="gate"),
    pytest.param({"rule_gates": {"what_comment": 17}}, id="rule-gate"),
    pytest.param({"exempt_paths": "*"}, id="paths"),
    pytest.param({"exempt_families": {"*": "clean_code"}}, id="families"),
    pytest.param({"data_boundary": {"enabled": "false"}}, id="boundary"),
]


@pytest.mark.parametrize("settings", MALFORMED)
def test_malformed_project_policy_fails_validation(tmp_path, settings) -> None:
    path = tmp_path / ".agent-discipline.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    with pytest.raises(config.ConfigLoadError):
        config.load_project_config(path)


@pytest.mark.parametrize("settings", MALFORMED)
def test_invalid_project_policy_reports_an_error_and_keeps_safe_defaults(tmp_path, capsys, settings) -> None:
    path = tmp_path / ".agent-discipline.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    effective = config.effective_config(cwd=tmp_path)

    assert config.gate_state("clean_code", effective) == "enforce"
    assert effective["exempt_paths"] == []
    assert capsys.readouterr().err


@pytest.mark.parametrize("raises,expectation", [
    pytest.param(False, nullcontext, id="normal"),
    pytest.param(True, lambda: pytest.raises(RuntimeError), id="exception"),
])
def test_config_lock_releases_without_replacing_its_inode(tmp_path, raises, expectation) -> None:
    path = tmp_path / ".agent-discipline.json"
    lock = tmp_path / ".agent-discipline.json.lock"
    lock.touch()
    identity = lock.stat().st_ino

    with expectation():
        with configure_store.locked(path):
            raise_if_present({False: None, True: RuntimeError("operation failed")}[raises])

    with lock.open("r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert os.fstat(stream.fileno()).st_ino == identity


def raise_if_present(error) -> None:
    """Keep exceptional setup separate because both exits need the same lock check."""
    if error is not None:
        raise error
