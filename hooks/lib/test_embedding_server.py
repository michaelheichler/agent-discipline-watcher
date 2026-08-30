from __future__ import annotations

import json
import os
import signal
import time
import urllib.request
from pathlib import Path

import pytest

from lib import embedding_server
from lib.model_artifacts import ModelPlatform, PythonRuntime

STUB = """
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, template, *args):
        return


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""
SILENT = "import time\ntime.sleep(60)\n"
ENTRY = ModelPlatform("stub", "mlx", (), PythonRuntime(("nothing==0.0.0",)))


@pytest.fixture(name="stub")
def _stub(tmp_path, monkeypatch):
    script = tmp_path / "stub_server.py"
    script.write_text(STUB, encoding="utf-8")
    monkeypatch.setattr(
        embedding_server, "command",
        lambda _entry, _root, port: ("python3", str(script), str(port)),
    )
    return script


def _wait_gone(pid: int, deadline: float) -> bool:
    while time.time() < deadline:
        if not embedding_server.process_alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_the_server_starts_on_a_free_port_and_records_it(stub, tmp_path) -> None:
    record = embedding_server.start(ENTRY, tmp_path)
    try:
        assert record.port > 0
        assert str(record.port) in record.url
        assert embedding_server.read_record(tmp_path) == record
        assert embedding_server.process_alive(record.pid)
    finally:
        embedding_server.stop(tmp_path)


def test_stopping_leaves_no_process_and_no_record(stub, tmp_path) -> None:
    record = embedding_server.start(ENTRY, tmp_path)

    assert embedding_server.stop(tmp_path) is True
    assert _wait_gone(record.pid, time.time() + 15)
    assert embedding_server.read_record(tmp_path) is None
    assert embedding_server.running_url(tmp_path) is None


def test_a_second_caller_reuses_the_running_server(stub, tmp_path) -> None:
    first = embedding_server.ensure_running(ENTRY, tmp_path)
    try:
        assert embedding_server.ensure_running(ENTRY, tmp_path) == first
    finally:
        embedding_server.stop(tmp_path)


def test_a_crashed_server_is_respawned_rather_than_reported_absent(stub, tmp_path) -> None:
    first = embedding_server.start(ENTRY, tmp_path)
    os.kill(first.pid, signal.SIGKILL)
    assert _wait_gone(first.pid, time.time() + 15)

    assert embedding_server.running_url(tmp_path) is None
    second = embedding_server.ensure_running(ENTRY, tmp_path)
    try:
        assert second != first.url
    finally:
        embedding_server.stop(tmp_path)


def test_a_server_that_never_answers_health_raises_and_records_nothing(tmp_path, monkeypatch) -> None:
    script = tmp_path / "silent.py"
    script.write_text(SILENT, encoding="utf-8")
    monkeypatch.setattr(
        embedding_server, "command", lambda _entry, _root, _port: ("python3", str(script))
    )
    monkeypatch.setattr(embedding_server, "READY_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(ValueError):
        embedding_server.start(ENTRY, tmp_path)

    assert embedding_server.read_record(tmp_path) is None


def test_a_runtime_that_exits_at_once_is_reported_with_its_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        embedding_server, "command", lambda _entry, _root, _port: ("python3", "-c", "raise SystemExit(3)")
    )

    with pytest.raises(ValueError) as raised:
        embedding_server.start(ENTRY, tmp_path)

    assert "3" in str(raised.value)


def test_the_record_survives_a_round_trip_through_disk(tmp_path) -> None:
    record = embedding_server.ServerRecord(os.getpid(), 1234, "http://127.0.0.1:1234/v1/embeddings", "stub", 5.0)
    embedding_server._write_record(tmp_path, record)

    assert embedding_server.read_record(tmp_path) == record
    assert embedding_server.running_url(tmp_path) == record.url


def test_a_missing_record_reads_as_absent(tmp_path) -> None:
    assert embedding_server.read_record(tmp_path) is None
    assert embedding_server.running_url(tmp_path) is None
    assert embedding_server.stop(tmp_path) is False


@pytest.mark.parametrize(
    ("pid", "port", "url"),
    [
        (-1, 1234, "http://127.0.0.1:1234/v1/embeddings"),
        (os.getpid(), 0, "http://127.0.0.1:0/v1/embeddings"),
        (os.getpid(), 1234, "https://unapproved.example/v1/embeddings"),
    ],
)
def test_a_malformed_record_is_ignored_before_kill_or_network(
    tmp_path, monkeypatch: pytest.MonkeyPatch, pid: int, port: int, url: str
) -> None:
    row = {
        "pid": pid,
        "port": port,
        "url": url,
        "platform": "stub",
        "started_at": 5.0,
    }
    embedding_server.record_path(tmp_path).write_text(json.dumps(row), encoding="utf-8")
    monkeypatch.setattr(embedding_server, "process_alive", lambda _pid: pytest.fail("probed malformed pid"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("probed malformed URL"))

    assert embedding_server.read_record(tmp_path) is None
    assert embedding_server.running_url(tmp_path) is None
    assert embedding_server.stop(tmp_path) is False


def test_an_oversized_record_is_ignored(tmp_path) -> None:
    embedding_server.record_path(tmp_path).write_text("x" * (embedding_server.MAX_RECORD_BYTES + 1), encoding="utf-8")

    assert embedding_server.read_record(tmp_path) is None


def test_the_worker_command_names_the_interpreter_and_the_weights(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(embedding_server, "ensure_weights", lambda _entry, _root: tmp_path / "weights")
    monkeypatch.setattr(embedding_server, "ensure_runtime", lambda _entry, _root: tmp_path / "python")

    arguments = embedding_server.command(ENTRY, tmp_path, 4321)

    assert arguments[0] == str(tmp_path / "python")
    assert arguments[1].endswith(embedding_server.WORKER_NAME)
    assert arguments[2:] == (str(tmp_path / "weights"), "4321")


def test_the_gguf_command_points_llama_server_at_the_quantized_file(tmp_path, monkeypatch) -> None:
    entry = Path("unused")
    monkeypatch.setattr(embedding_server, "ensure_weights", lambda _entry, _root: tmp_path / "weights")
    monkeypatch.setattr(embedding_server, "ensure_runtime", lambda _entry, _root: tmp_path / "llama-server")
    from lib.model_artifacts import resolve

    arguments = embedding_server.command(resolve("Linux", "x86_64"), tmp_path, 4321)

    assert arguments[0] == str(tmp_path / "llama-server")
    assert "--embeddings" in arguments
    assert arguments[arguments.index("--port") + 1] == "4321"
    assert str(entry) not in arguments
