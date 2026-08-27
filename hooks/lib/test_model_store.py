from __future__ import annotations

import hashlib
import http.server
import tarfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from lib import model_store
from lib.model_artifacts import Artifact, ArchiveRuntime, ModelPlatform, PythonRuntime

BODY = b"the quick brown fox jumps over the lazy dog\n" * 64
DIGEST = hashlib.sha256(BODY).hexdigest()


class _Handler(http.server.BaseHTTPRequestHandler):
    truncate = False
    requests = 0

    def do_GET(self) -> None:
        type(self).requests += 1
        payload = BODY[: len(BODY) // 2] if self.truncate else BODY
        start = 0
        requested = self.headers.get("Range")
        if requested:
            start = int(requested.removeprefix("bytes=").rstrip("-"))
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(payload) - start))
        self.end_headers()
        self.wfile.write(payload[start:])

    def log_message(self, template: str, *args: object) -> None:
        return


@pytest.fixture(name="server")
def _server() -> Iterator[str]:
    _Handler.truncate = False
    _Handler.requests = 0
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def _artifact(server: str) -> Artifact:
    return Artifact("weights.bin", f"{server}/weights.bin", DIGEST, len(BODY))


def test_a_matching_body_lands_at_its_destination(server, tmp_path) -> None:
    artifact = _artifact(server)

    path = model_store.ensure_artifact(artifact, tmp_path)

    assert path.read_bytes() == BODY
    assert not list(tmp_path.glob("*.partial"))


def test_a_truncated_body_is_rejected_and_never_lands(server, tmp_path) -> None:
    _Handler.truncate = True
    artifact = _artifact(server)

    with pytest.raises(ValueError) as raised:
        model_store.ensure_artifact(artifact, tmp_path)

    assert DIGEST in str(raised.value)
    assert not (tmp_path / artifact.name).exists()


def test_a_wrong_digest_is_rejected_even_at_the_right_length(server, tmp_path) -> None:
    artifact = Artifact("weights.bin", f"{server}/weights.bin", "0" * 64, len(BODY))

    with pytest.raises(ValueError):
        model_store.ensure_artifact(artifact, tmp_path)

    assert not (tmp_path / artifact.name).exists()


def test_an_artifact_already_on_disk_costs_no_request(tmp_path) -> None:
    artifact = Artifact("weights.bin", "http://127.0.0.1:1/weights.bin", DIGEST, len(BODY))
    (tmp_path / artifact.name).write_bytes(BODY)

    assert model_store.ensure_artifact(artifact, tmp_path).read_bytes() == BODY


def test_a_half_written_partial_resumes_rather_than_restarting(server, tmp_path) -> None:
    artifact = _artifact(server)
    partial = tmp_path / (artifact.name + model_store.PARTIAL_SUFFIX)
    partial.write_bytes(BODY[:100])

    assert model_store.ensure_artifact(artifact, tmp_path).read_bytes() == BODY


def test_a_second_caller_waits_instead_of_starting_its_own_download(server, tmp_path) -> None:
    artifact = _artifact(server)
    callers = [threading.Thread(target=model_store.ensure_artifact, args=(artifact, tmp_path)) for _ in range(4)]

    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=30)

    assert (tmp_path / artifact.name).read_bytes() == BODY
    assert _Handler.requests == 1


def _archive_platform(server: str, tmp_path: Path) -> tuple[ModelPlatform, Path]:
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "llama-server").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    served = tmp_path / "served"
    served.mkdir()
    archive = served / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(payload / "llama-server", arcname="payload/llama-server")
    runtime = ArchiveRuntime(
        "payload/llama-server",
        Artifact("runtime.tar.gz", f"{server}/runtime.tar.gz", _digest_of(archive), archive.stat().st_size),
    )
    return ModelPlatform("test", "gguf", (), runtime), archive


def _digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_an_archive_runtime_lands_executable_at_its_named_server(tmp_path, monkeypatch) -> None:
    entry, archive = _archive_platform("http://placeholder", tmp_path)
    monkeypatch.setattr(model_store, "download", lambda _artifact, destination: destination.write_bytes(archive.read_bytes()))

    server = model_store.ensure_runtime(entry, tmp_path / "root")

    assert server.is_file()
    assert server.stat().st_mode & 0o111


def test_a_python_runtime_reports_the_interpreter_it_would_build(tmp_path) -> None:
    entry = ModelPlatform("test", "mlx", (), PythonRuntime(("nothing==0.0.0",)))

    expected = model_store.runtime_root(entry, tmp_path) / model_store.VENV_DIRNAME / "bin" / "python"
    expected.parent.mkdir(parents=True)
    expected.write_text("", encoding="utf-8")

    assert model_store.ensure_runtime(entry, tmp_path) == expected
