from __future__ import annotations

import pytest

from lib import host, judge, judge_provider


def test_omp_is_detected_from_its_own_marker() -> None:
    """Split the hosts because OMP also sets the Claude compat marker."""
    assert host.is_omp_host({"OMPCODE": "1"})
    assert host.is_omp_host({"OMPCODE": "1", "CLAUDECODE": "1"})

    assert not host.is_omp_host({})
    assert not host.is_omp_host({"OMPCODE": "  "})
    assert not host.is_omp_host({"CLAUDECODE": "1"})


def test_claude_is_not_claimed_while_running_under_omp() -> None:
    """Reject the shared marker because OMP exports it for compatibility."""
    assert host.is_claude_host({"CLAUDECODE": "1"})

    assert not host.is_claude_host({"CLAUDECODE": "1", "OMPCODE": "1"})
    assert not host.is_claude_host({})


def test_each_marker_resolves_to_exactly_one_host() -> None:
    """Return one name because a runtime must never load two adapters."""
    assert host.current_host({"OMPCODE": "1"}) == host.OMP
    assert host.current_host({"ADW_CODEX_HOOK": "1"}) == host.CODEX
    assert host.current_host({"CLAUDE_CODE_IS_COWORK": "1"}) == host.COWORK
    assert host.current_host({"CLAUDECODE": "1"}) == host.CLAUDE


def test_omp_outranks_the_claude_compat_marker() -> None:
    """Read OMP first because it exports CLAUDECODE for compatibility."""
    assert host.current_host({"OMPCODE": "1", "CLAUDECODE": "1"}) == host.OMP


def test_codex_outranks_a_stray_claude_marker() -> None:
    """Read the Codex marker first because its bridge runs under a borrowed environment."""
    assert host.current_host({"ADW_CODEX_HOOK": "1", "CLAUDECODE": "1"}) == host.CODEX


def test_cowork_outranks_claude_because_it_shares_the_engine() -> None:
    """Separate Cowork because its VM never reads the host home directory."""
    assert host.current_host({"CLAUDE_CODE_IS_COWORK": "1", "CLAUDECODE": "1"}) == host.COWORK


def test_an_unknown_host_raises_and_never_falls_back() -> None:
    """Refuse a silent default because a wrong adapter would gate nothing."""
    with pytest.raises(host.UnknownHostError):
        host.current_host({})

    with pytest.raises(host.UnknownHostError):
        host.current_host({"SOME_OTHER_AGENT": "1"})


def test_the_supported_names_stay_a_closed_set() -> None:
    """Pin the roster because a fifth runtime must fail the suite before it ships."""
    assert host.SUPPORTED == (host.CLAUDE, host.CODEX, host.OMP, host.COWORK)


def test_the_claude_cli_judge_is_refused_under_omp(monkeypatch) -> None:
    """Refuse the CLI because OMP must judge with its own models."""
    monkeypatch.delenv(judge.RECURSION_GUARD, raising=False)
    monkeypatch.delenv(host.OMP_ENV, raising=False)
    assert judge.available() is True

    monkeypatch.setenv(host.OMP_ENV, "1")
    assert judge.available() is False


def test_the_judge_availability_gate_reads_host_identity(monkeypatch) -> None:
    """Derive the gate from identity because a raw env read let two hosts claim one session."""
    monkeypatch.delenv(judge_provider.RECURSION_GUARD, raising=False)
    monkeypatch.delenv(host.OMP_ENV, raising=False)
    assert judge_provider.available() is True

    monkeypatch.setenv(host.OMP_ENV, "1")
    assert judge_provider.available() is False
