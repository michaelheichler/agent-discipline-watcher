import os
import socket
import time

import pytest

from lib import embedding_lease, embedding_session


def _closed_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@pytest.fixture(name="opted_in", autouse=True)
def _opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set for this file because the bracket is off until a reader for the vectors exists."""
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")
    monkeypatch.setattr(embedding_session, "CONSUMER_REGISTERED", True)


def test_without_a_consumer_a_prompt_never_loads_the_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embedding_session, "CONSUMER_REGISTERED", False)
    monkeypatch.setattr(embedding_session, "ensure_loaded", lambda *_args: pytest.fail("loaded without a consumer"))

    assert embedding_session.open_turn("alpha", str(tmp_path)) is None
    assert not list(tmp_path.glob("*.lease.json"))


def test_without_a_consumer_close_turn_still_releases_a_stale_lease(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embedding_session, "CONSUMER_REGISTERED", False)
    embedding_lease.acquire("alpha", 1000.0, tmp_path, os.getpid())

    embedding_session.close_turn("alpha", str(tmp_path))

    assert embedding_lease.live_sessions(1001.0, tmp_path) == ()


@pytest.fixture(name="absent_server")
def _absent_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADW_EMBEDDING_URLS", f"http://127.0.0.1:{_closed_port()}/v1/embeddings")


def test_the_switch_keeps_both_ends_quiet(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(embedding_session.DISABLE_ENV, "1")

    assert embedding_session.open_turn("alpha", str(tmp_path)) is None
    assert embedding_session.close_turn("alpha", str(tmp_path)) is False
    assert not list(tmp_path.glob("*.lease.json"))


def test_a_missing_session_id_never_takes_a_lease(tmp_path) -> None:
    assert embedding_session.open_turn("", str(tmp_path)) is None
    assert not list(tmp_path.glob("*.lease.json"))


def test_an_absent_server_retains_demand_during_background_start(absent_server, tmp_path) -> None:
    assert embedding_session.open_turn("alpha", str(tmp_path)) is None
    assert len(list(tmp_path.glob("*.lease.json"))) == 1


def test_an_unsafe_session_id_is_swallowed_rather_than_failing_the_turn(tmp_path) -> None:
    assert embedding_session.open_turn("../escape", str(tmp_path)) is None
    assert embedding_session.close_turn("../escape", str(tmp_path)) is False


def test_the_lease_root_follows_the_configured_state_root(tmp_path) -> None:
    """Asserted because a test that isolates its state root once reached the real data home through this path."""
    root = embedding_session.lease_root_for({"state_root": str(tmp_path / "state")})

    assert root == str(tmp_path / embedding_session.LEASE_DIRECTORY_NAME)
    assert embedding_session.lease_root_for({}) is None


def test_an_absent_server_provisions_in_the_background(absent_server, tmp_path, monkeypatch) -> None:
    asked = []
    monkeypatch.setattr(embedding_session, "start_detached", asked.append)

    assert embedding_session.open_turn("alpha", str(tmp_path)) is None
    assert asked == [embedding_session.default_root()]


def test_close_turn_releases_the_lease_the_turn_took(tmp_path) -> None:
    embedding_lease.acquire("alpha", 1000.0, tmp_path, os.getpid())

    embedding_session.close_turn("alpha", str(tmp_path))

    assert embedding_lease.live_sessions(1001.0, tmp_path) == ()


def test_disabling_embeddings_does_not_prevent_releasing_an_existing_lease(tmp_path, monkeypatch) -> None:
    embedding_lease.acquire("alpha", 1000.0, tmp_path, os.getpid())
    monkeypatch.setenv(embedding_session.DISABLE_ENV, "1")

    embedding_session.close_turn("alpha", str(tmp_path))

    assert embedding_lease.live_sessions(1001.0, tmp_path) == ()


@pytest.mark.parametrize("managed", [True, False])
def test_only_a_managed_answering_worker_needs_a_supervisor(tmp_path, monkeypatch, managed) -> None:
    url = "http://127.0.0.1:1234/v1/embeddings"
    asked = []
    monkeypatch.setattr(embedding_session, "ensure_loaded", lambda *_args: url)
    monkeypatch.setattr(embedding_session, "running_url", lambda _root: url if managed else None)
    monkeypatch.setattr(embedding_session, "start_detached", asked.append)

    assert embedding_session.open_turn("alpha", str(tmp_path)) == url
    assert asked == ([embedding_session.default_root()] if managed else [])


def test_failed_cleanup_is_reported_without_raising(tmp_path, monkeypatch, capsys) -> None:
    def fail_release(*_args) -> bool:
        raise PermissionError("cannot signal worker")

    monkeypatch.setattr(embedding_session, "release", fail_release)

    assert embedding_session.close_turn("alpha", str(tmp_path)) is False
    assert "embedding cleanup failed: cannot signal worker" in capsys.readouterr().err


def test_renew_turn_keeps_a_long_turn_holding_the_model(tmp_path) -> None:
    embedding_lease.acquire("alpha", 1000.0, tmp_path, os.getpid())

    assert embedding_session.renew_turn("alpha", str(tmp_path)) is True
    assert embedding_lease.live_sessions(time.time(), tmp_path) == ("alpha",)


def test_renew_turn_without_a_session_does_nothing(tmp_path) -> None:
    assert embedding_session.renew_turn("", str(tmp_path)) is False


def test_renew_turn_reports_a_failure_without_raising(tmp_path, capsys) -> None:
    assert embedding_session.renew_turn("../escape", str(tmp_path)) is False
    assert "embedding renewal failed" in capsys.readouterr().err
