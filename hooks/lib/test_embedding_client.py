import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lib import embedding_client, embedding_lease, embedding_server


def _echo_body(payload: dict) -> dict:
    texts = payload.get("input", ())
    return {"data": [{"embedding": [float(len(text)), 0.5]} for text in texts]}


class _EmbeddingHandler(BaseHTTPRequestHandler):
    """A real socket server rather than a patched urlopen, because the contract under test is HTTP behaviour."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        queue = self.server.responses
        self.server.received.append((self.path, payload))
        status, body = queue.pop(0) if queue else (200, _echo_body(payload))
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:  # pylint: disable=redefined-builtin
        return


@pytest.fixture(name="server")
def _server(monkeypatch: pytest.MonkeyPatch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _EmbeddingHandler)
    httpd.received = []
    httpd.responses = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    monkeypatch.setenv("ADW_EMBEDDING_URL", f"http://127.0.0.1:{port}/v1/embeddings")
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _embed(texts: tuple[str, ...], config: dict | None = None) -> tuple | None:
    return embedding_client.embed(texts, config, retry_delays=(0.0, 0.0))


def _closed_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_embed_returns_one_vector_per_input(server) -> None:
    vectors = _embed(("alpha", "bee"))

    assert vectors == ((5.0, 0.5), (3.0, 0.5))
    _path, payload = server.received[0]
    assert payload["model"] == embedding_client.DEFAULT_MODEL
    assert payload["input"] == ["alpha", "bee"]


def test_an_empty_request_never_reaches_the_server(server) -> None:
    assert _embed(()) == ()
    assert server.received == []


def test_an_absent_server_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADW_EMBEDDING_URL", f"http://127.0.0.1:{_closed_port()}/v1/embeddings")

    assert _embed(("alpha",)) is None


def test_a_refused_first_host_falls_through_to_the_second(server, monkeypatch) -> None:
    live = f"http://127.0.0.1:{server.server_address[1]}/v1/embeddings"
    monkeypatch.setenv(
        "ADW_EMBEDDING_URLS",
        f"http://127.0.0.1:{_closed_port()}/v1/embeddings,{live}",
    )

    assert _embed(("alpha",)) == ((5.0, 0.5),)
    assert len(server.received) == 1


def test_both_hosts_absent_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ADW_EMBEDDING_URLS",
        f"http://127.0.0.1:{_closed_port()}/v1/embeddings,http://127.0.0.1:{_closed_port()}/v1/embeddings",
    )

    assert _embed(("alpha",)) is None


def test_a_client_error_is_raised_rather_than_swallowed(server) -> None:
    server.responses.append((404, {"error": "unknown model"}))

    with pytest.raises(OSError):
        _embed(("alpha",))


def test_a_server_error_is_retried_and_then_reported_as_absent(server) -> None:
    server.responses.extend([(503, {}), (503, {}), (503, {})])

    assert _embed(("alpha",)) is None
    assert len(server.received) == 3


def test_a_missing_vector_raises_instead_of_returning_short(server) -> None:
    server.responses.append((200, {"data": [{"embedding": [1.0]}]}))

    with pytest.raises(ValueError):
        _embed(("alpha", "bee"))


def test_a_response_without_a_data_list_raises(server) -> None:
    server.responses.append((200, {"object": "list"}))

    with pytest.raises(ValueError):
        _embed(("alpha",))


def test_release_drops_the_lease_and_leaves_the_worker_to_the_supervisor(server, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embedding_server, "_stop", lambda _root: pytest.fail("release terminated the worker"))
    assert embedding_client.ensure_loaded("alpha", 1000.0, tmp_path, os.getpid()) is not None
    assert embedding_client.ensure_loaded("beta", 1000.0, tmp_path, os.getpid()) is not None

    assert embedding_client.release("alpha", tmp_path) is True
    assert embedding_lease.live_sessions(1001.0, tmp_path) == ("beta",)
    assert embedding_client.release("beta", tmp_path) is True
    assert not list(tmp_path.glob("*.lease.json"))


def test_releasing_a_lease_never_taken_reports_false(tmp_path) -> None:
    assert embedding_client.release("solo", tmp_path) is False


def test_an_absent_server_keeps_the_lease_while_provisioning(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADW_EMBEDDING_URL", f"http://127.0.0.1:{_closed_port()}/v1/embeddings")

    assert embedding_client.ensure_loaded("solo", 1000.0, tmp_path, os.getpid()) is None
    assert embedding_lease.live_sessions(1001.0, tmp_path) == ("solo",)


def test_another_project_keeps_the_machine_wide_server_loaded(server, tmp_path) -> None:
    embedding_client.ensure_loaded("alpha", 1000.0, tmp_path / "project-a", os.getpid())
    embedding_client.ensure_loaded("beta", 1000.0, tmp_path / "project-b", os.getpid())

    embedding_client.release("alpha", tmp_path / "project-a")

    assert embedding_lease.has_live_leases(embedding_client.default_root(), 1001.0)
    embedding_client.release("beta", tmp_path / "project-b")
    assert not embedding_lease.has_live_leases(embedding_client.default_root(), 1001.0)


@pytest.mark.parametrize("variable", ["ADW_EMBEDDING_URL", "ADW_EMBEDDING_URLS"])
def test_an_unapproved_embedding_url_never_receives_private_text(server, monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    monkeypatch.delenv("ADW_EMBEDDING_URL", raising=False)
    monkeypatch.delenv("ADW_EMBEDDING_URLS", raising=False)
    monkeypatch.setenv(variable, "https://unapproved.example/v1/embeddings")

    assert _embed(("PRIVATE-SOURCE",)) is None
    assert server.received == []


def test_disabled_project_boundary_blocks_remote_source_egress(server, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADW_EMBEDDING_LOCAL_ONLY", "0")
    monkeypatch.setenv("ADW_EMBEDDING_APPROVED_HOSTS", "approved.example")
    monkeypatch.setenv("ADW_EMBEDDING_URL", "https://approved.example/v1/embeddings")

    assert _embed(("PRIVATE-SOURCE",), {"data_boundary": {"enabled": False}}) is None
    assert server.received == []


def test_oversized_input_is_rejected_before_network_io(server) -> None:
    with pytest.raises(ValueError):
        _embed(("x",) * (embedding_client.MAX_INPUTS + 1))

    assert server.received == []


def test_client_and_server_share_one_url_validator() -> None:
    assert embedding_client.parse_endpoint is embedding_server.parse_endpoint
    assert embedding_client.is_loopback_host is embedding_server.is_loopback_host


@pytest.mark.parametrize(
    "url",
    [
        "http://user:secret@127.0.0.1:1234/v1/embeddings",
        "http://127.0.0.1:1234/v1/embeddings?next=1",
        "http://127.0.0.1:0/v1/embeddings",
        "ftp://127.0.0.1:1234/v1/embeddings",
        "http://127.0.0.1:1234/v1/em beddings",
    ],
)
def test_a_malformed_url_is_refused_by_both_sides(url: str) -> None:
    assert embedding_server.parse_endpoint(url) is None
    assert not embedding_client._approved_url(url)
    assert not embedding_server._loopback_url(url)


def test_oversized_embedding_response_is_rejected(server) -> None:
    server.responses.append(
        (
            200,
            {"data": [{"embedding": [1.0]}] * (embedding_client.MAX_RESPONSE_ROWS + 1)},
        )
    )

    with pytest.raises(ValueError):
        _embed(("alpha",))
