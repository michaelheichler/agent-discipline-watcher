import os
import socket

import pytest

from lib import embedding_lease, embedding_session


def _closed_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@pytest.fixture(name="no_provisioning", autouse=True)
def _no_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stubbed for every test in this file because the real call downloads a model into the user's home."""
    monkeypatch.setattr(embedding_session, "start_detached", lambda _root: None)


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


def test_an_absent_server_leaves_no_lease_and_no_exception(absent_server, tmp_path) -> None:
    assert embedding_session.open_turn("alpha", str(tmp_path)) is None
    assert not list(tmp_path.glob("*.lease.json"))


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
