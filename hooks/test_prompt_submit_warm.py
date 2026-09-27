from __future__ import annotations

import time
from pathlib import Path

import pytest

import prompt_submit
from lib import embedding_lease, embedding_session, host


@pytest.fixture(name="cold_worker")
def _cold_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[list, dict]:
    """Faked, because a test must never load the real model."""
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")
    for name in embedding_session.USER_URL_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(embedding_session, "provisioned", lambda: True)
    launched: list = []
    monkeypatch.setattr(embedding_session, "start_detached", launched.append)
    return launched, {"state_root": str(tmp_path / "state")}


def _on_host(monkeypatch: pytest.MonkeyPatch, marker: str) -> None:
    for name in (host.OMP_ENV, host.CODEX_ENV, host.COWORK_ENV, host.CLAUDE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(marker, "1")


def _prompt(config: dict) -> dict:
    return prompt_submit.run({"prompt": "Implement it.", "cwd": "", "session_id": "s1"}, config)


def _leases(config: dict) -> tuple[str, ...]:
    return embedding_lease.live_sessions(time.time(), embedding_session.lease_root_for(config))


def test_a_codex_prompt_restarts_the_worker_the_last_stop_released(cold_worker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Restarted, because Stop unloads the model every turn."""
    launched, config = cold_worker
    _on_host(monkeypatch, host.CODEX_ENV)

    started = time.monotonic()
    _prompt(config)

    assert time.monotonic() - started < 2.0
    assert launched == [embedding_session.default_root()]
    assert _leases(config) == ("s1",)


def test_a_claude_prompt_leaves_the_model_to_the_async_route(cold_worker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipped, because the Claude vote waits 120 seconds."""
    launched, config = cold_worker
    _on_host(monkeypatch, host.CLAUDE_ENV)
    monkeypatch.setattr(embedding_session, "CONSUMER_REGISTERED", False)

    _prompt(config)

    assert launched == []
    assert _leases(config) == ()
