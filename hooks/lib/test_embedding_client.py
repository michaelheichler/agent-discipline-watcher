import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lib import embedding_client


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
    monkeypatch.setattr(embedding_client, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _closed_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_embed_returns_one_vector_per_input(server) -> None:
    vectors = embedding_client.embed(("alpha", "bee"))

    assert vectors == ((5.0, 0.5), (3.0, 0.5))
    _path, payload = server.received[0]
    assert payload["model"] == embedding_client.DEFAULT_MODEL
    assert payload["input"] == ["alpha", "bee"]


def test_an_empty_request_never_reaches_the_server(server) -> None:
    assert embedding_client.embed(()) == ()
    assert server.received == []


def test_an_absent_server_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADW_EMBEDDING_URL", f"http://127.0.0.1:{_closed_port()}/v1/embeddings")
    monkeypatch.setattr(embedding_client, "RETRY_DELAYS_SECONDS", ())

    assert embedding_client.embed(("alpha",)) is None


def test_a_refused_first_host_falls_through_to_the_second(server, monkeypatch) -> None:
    live = f"http://127.0.0.1:{server.server_address[1]}/v1/embeddings"
    monkeypatch.setenv(
        "ADW_EMBEDDING_URLS",
        f"http://127.0.0.1:{_closed_port()}/v1/embeddings,{live}",
    )

    assert embedding_client.embed(("alpha",)) == ((5.0, 0.5),)
    assert len(server.received) == 1


def test_both_hosts_absent_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_client, "RETRY_DELAYS_SECONDS", ())
    monkeypatch.setenv(
        "ADW_EMBEDDING_URLS",
        f"http://127.0.0.1:{_closed_port()}/v1/embeddings,http://127.0.0.1:{_closed_port()}/v1/embeddings",
    )

    assert embedding_client.embed(("alpha",)) is None


def test_a_client_error_is_raised_rather_than_swallowed(server) -> None:
    server.responses.append((404, {"error": "unknown model"}))

    with pytest.raises(OSError):
        embedding_client.embed(("alpha",))


def test_a_server_error_is_retried_and_then_reported_as_absent(server) -> None:
    server.responses.extend([(503, {}), (503, {}), (503, {})])

    assert embedding_client.embed(("alpha",)) is None
    assert len(server.received) == 3


def test_a_missing_vector_raises_instead_of_returning_short(server) -> None:
    server.responses.append((200, {"data": [{"embedding": [1.0]}]}))

    with pytest.raises(ValueError):
        embedding_client.embed(("alpha", "bee"))


def test_a_response_without_a_data_list_raises(server) -> None:
    server.responses.append((200, {"object": "list"}))

    with pytest.raises(ValueError):
        embedding_client.embed(("alpha",))


def test_the_last_session_stops_the_server_and_the_others_do_not(server, tmp_path, monkeypatch) -> None:
    stopped = []

    def _record_stop(root) -> bool:
        stopped.append(root)
        return True

    monkeypatch.setattr(embedding_client, "stop", _record_stop)

    assert embedding_client.ensure_loaded("alpha", 1000.0, tmp_path, os.getpid()) is not None
    assert embedding_client.ensure_loaded("beta", 1000.0, tmp_path, os.getpid()) is not None
    assert embedding_client.release("alpha", 1001.0, tmp_path) is False
    assert embedding_client.release("beta", 1002.0, tmp_path) is True
    assert stopped == [embedding_client.default_root()]


def test_a_session_that_never_loaded_stops_nothing(server, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embedding_client, "stop", lambda _root: False)
    embedding_client.ensure_loaded("solo", 1000.0, tmp_path, os.getpid())

    assert embedding_client.release("solo", 1001.0, tmp_path) is False
    assert not list(tmp_path.glob("*.lease.json"))


def test_an_absent_server_does_not_leave_a_lease_behind(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADW_EMBEDDING_URL", f"http://127.0.0.1:{_closed_port()}/v1/embeddings")
    monkeypatch.setattr(embedding_client, "RETRY_DELAYS_SECONDS", ())

    assert embedding_client.ensure_loaded("solo", 1000.0, tmp_path, os.getpid()) is None
    assert not list(tmp_path.glob("*.lease.json"))
