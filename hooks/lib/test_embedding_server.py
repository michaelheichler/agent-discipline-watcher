from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from lib import embedding_client, embedding_lease, embedding_server
from lib.model_artifacts import ModelPlatform, PythonRuntime

STUB = """
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok", "nonce": os.environ.get("ADW_EMBEDDING_NONCE", "")}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, template, *args):
        return


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""
SILENT = "import time\ntime.sleep(60)\n"
ENTRY = ModelPlatform("stub", "mlx", (), PythonRuntime(("nothing==0.0.0",)))
SUPERVISOR = """
import sys
import time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib import embedding_server
from lib.model_artifacts import ModelPlatform, PythonRuntime

root = Path(sys.argv[2])
def provision(entry, directory):
    if sys.argv[4] == "slow":
        (root / "provisioning").touch()
        while not (root / "continue").exists():
            time.sleep(0.02)
    return lambda port: (sys.executable, sys.argv[3], str(port))

embedding_server.LEASE_POLL_SECONDS = 0.05
embedding_server.supervise(ModelPlatform("stub", "mlx", (), PythonRuntime(())), root, prepare=provision)
"""


def _command(*arguments: str):
    return lambda _entry, _root: lambda port: ("python3", *arguments, str(port))


def _start(stub: Path, root: Path) -> embedding_server.ServerRecord:
    return embedding_server.start(ENTRY, root, prepare=_command(str(stub)))


@pytest.fixture(name="stub")
def _stub(tmp_path):
    script = tmp_path / "stub_server.py"
    script.write_text(STUB, encoding="utf-8")
    return script


def _wait_gone(pid: int, deadline: float) -> bool:
    while time.time() < deadline:
        if not embedding_server.process_alive(pid):
            return True
        time.sleep(0.05)
    return False


def _wait_until(predicate) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("embedding lifecycle condition did not become true")


@pytest.fixture(name="supervisor")
def _supervisor(stub, monkeypatch):
    root = embedding_server.default_root()
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(embedding_client, "probe", lambda: None)
    children = []

    def launch(*, slow=False):
        child = subprocess.Popen(
            (sys.executable, "-c", SUPERVISOR, str(Path(__file__).parents[1]),
             str(root), str(stub), "slow" if slow else "normal"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        children.append(child)
        return child

    yield root, launch
    (root / "continue").touch()
    for child in children:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)
    embedding_server.stop(root)


def test_the_server_starts_on_a_free_port_and_records_it(stub, tmp_path) -> None:
    record = _start(stub, tmp_path)
    try:
        assert record.port > 0
        assert str(record.port) in record.url
        assert embedding_server.read_record(tmp_path) == record
        assert embedding_server.process_alive(record.pid)
    finally:
        embedding_server.stop(tmp_path)


def test_each_worker_launch_starts_a_fresh_log(stub, tmp_path) -> None:
    (tmp_path / embedding_server.LOG_NAME).write_text("previous launch output\n", encoding="utf-8")

    _start(stub, tmp_path)
    try:
        assert "previous launch output" not in (tmp_path / embedding_server.LOG_NAME).read_text(encoding="utf-8")
    finally:
        embedding_server.stop(tmp_path)


def test_stopping_leaves_no_process_and_no_record(stub, tmp_path) -> None:
    record = _start(stub, tmp_path)

    assert embedding_server.stop(tmp_path) is True
    assert _wait_gone(record.pid, time.time() + 15)
    assert embedding_server.read_record(tmp_path) is None
    assert embedding_server.running_url(tmp_path) is None


def test_stopping_a_worker_that_ignores_sigterm_waits_for_sigkill(stub, tmp_path, monkeypatch) -> None:
    stub.write_text("import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" + STUB, encoding="utf-8")
    monkeypatch.setattr(embedding_server, "STOP_GRACE_SECONDS", 0.25)
    record = _start(stub, tmp_path)

    assert embedding_server.stop(tmp_path) is True
    assert not embedding_server.process_alive(record.pid)
    assert embedding_server.read_record(tmp_path) is None


def test_stop_during_provisioning_cannot_leave_a_late_worker(supervisor, tmp_path) -> None:
    root, launch = supervisor
    leases = tmp_path / "leases"
    embedding_client.ensure_loaded("alpha", time.time(), leases, os.getpid())
    child = launch(slow=True)
    _wait_until(lambda: (root / "provisioning").exists())

    assert embedding_client.release("alpha", leases) is True
    (root / "continue").touch()

    assert child.wait(timeout=10) == 0
    assert embedding_server.read_record(root) is None
    assert not (root / embedding_server.LOG_NAME).exists()


def test_stop_can_terminate_a_worker_before_health_is_ready(supervisor, stub, tmp_path) -> None:
    root, launch = supervisor
    stub.write_text(SILENT, encoding="utf-8")
    leases = tmp_path / "leases"
    embedding_client.ensure_loaded("alpha", time.time(), leases, os.getpid())
    child = launch()
    _wait_until(lambda: embedding_server.read_record(root) is not None)
    record = embedding_server.read_record(root)

    assert embedding_client.release("alpha", leases) is True

    assert child.wait(timeout=10) == 0
    assert not embedding_server.process_alive(record.pid)
    assert embedding_server.read_record(root) is None


@pytest.mark.parametrize("ending", ["stop", "expiry", "dead-owner"])
def test_supervisor_unloads_without_requiring_another_prompt(supervisor, tmp_path, ending) -> None:
    root, launch = supervisor
    leases = tmp_path / "leases"
    embedding_client.ensure_loaded("alpha", time.time(), leases, os.getpid())
    child = launch()
    _wait_until(lambda: embedding_server.running_url(root) is not None)
    record = embedding_server.read_record(root)
    _wait_until(lambda: embedding_server._answers(f"http://127.0.0.1:{record.port}/health"))

    if ending == "stop":
        assert embedding_client.release("alpha", leases) is True
    else:
        renewed = time.time() - embedding_lease.LEASE_TTL_SECONDS - 1 if ending == "expiry" else time.time()
        pid = 2 ** 22 if ending == "dead-owner" else os.getpid()
        embedding_lease.acquire("alpha", renewed, leases, pid)

    assert child.wait(timeout=10) == 0
    assert not embedding_server.process_alive(record.pid)
    assert embedding_server.read_record(root) is None
    assert embedding_lease.live_sessions(time.time(), leases) == ()


def test_parallel_supervisors_reuse_one_worker_and_honor_other_projects(supervisor, tmp_path) -> None:
    root, launch = supervisor
    leases_a, leases_b = tmp_path / "a", tmp_path / "b"
    embedding_client.ensure_loaded("alpha", time.time(), leases_a, os.getpid())
    first = launch()
    _wait_until(lambda: embedding_server.running_url(root) is not None)
    record = embedding_server.read_record(root)
    embedding_client.ensure_loaded("beta", time.time(), leases_b, os.getpid())

    assert launch().wait(timeout=10) == 0
    assert embedding_client.release("alpha", leases_a) is True
    time.sleep(0.2)
    assert embedding_server.read_record(root) == record
    assert embedding_server.process_alive(record.pid)
    assert first.poll() is None
    assert embedding_client.release("beta", leases_b) is True
    assert first.wait(timeout=10) == 0


def test_the_supervisor_respawns_a_crashed_worker(supervisor, tmp_path) -> None:
    root, launch = supervisor
    leases = tmp_path / "leases"
    embedding_client.ensure_loaded("alpha", time.time(), leases, os.getpid())
    child = launch()
    _wait_until(lambda: embedding_server.running_url(root) is not None)
    first = embedding_server.read_record(root)
    _wait_until(lambda: embedding_server._answers(f"http://127.0.0.1:{first.port}/health", first.nonce))
    time.sleep(4 * embedding_server.READY_POLL_SECONDS)

    os.kill(first.pid, signal.SIGKILL)
    assert _wait_gone(first.pid, time.time() + 15)
    _wait_until(lambda: embedding_server.running_url(root) is not None)

    assert embedding_server.read_record(root).pid != first.pid
    embedding_client.release("alpha", leases)
    assert child.wait(timeout=10) == 0


def test_a_server_that_never_answers_health_raises_and_records_nothing(tmp_path, monkeypatch) -> None:
    script = tmp_path / "silent.py"
    script.write_text(SILENT, encoding="utf-8")
    monkeypatch.setattr(embedding_server, "READY_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(ValueError):
        embedding_server.start(ENTRY, tmp_path, prepare=lambda _entry, _root: lambda _port: ("python3", str(script)))

    assert embedding_server.read_record(tmp_path) is None


def test_a_runtime_that_exits_at_once_is_reported_with_its_status(tmp_path) -> None:
    with pytest.raises(ValueError) as raised:
        embedding_server.start(ENTRY, tmp_path, prepare=lambda _entry, _root: lambda _port: ("python3", "-c", "raise SystemExit(3)"))

    assert "3" in str(raised.value)


def test_a_record_write_failure_does_not_orphan_the_worker(stub, tmp_path, monkeypatch) -> None:
    spawned = []
    original_spawn = embedding_server._spawn

    def spawn(arguments, root, nonce, **options) -> subprocess.Popen:
        child = original_spawn(arguments, root, nonce, **options)
        spawned.append(child)
        return child

    def fail_record(_root, _record):
        raise OSError("disk full")

    monkeypatch.setattr(embedding_server, "_spawn", spawn)
    monkeypatch.setattr(embedding_server, "_write_record", fail_record)
    with pytest.raises(OSError, match="disk full"):
        _start(stub, tmp_path)

    assert len(spawned) == 1
    assert not embedding_server.process_alive(spawned[0].pid)
    assert embedding_server.read_record(tmp_path) is None


def _own_record(process_start: str | None = None) -> embedding_server.ServerRecord:
    started = process_start or embedding_server.process_start(os.getpid())
    return embedding_server.ServerRecord(
        os.getpid(), 1234, "http://127.0.0.1:1234/v1/embeddings", "stub", 5.0, started, "nonce"
    )


def test_the_record_survives_a_round_trip_through_disk(tmp_path) -> None:
    record = _own_record()
    embedding_server._write_record(tmp_path, record)

    assert embedding_server.read_record(tmp_path) == record
    assert embedding_server.running_url(tmp_path) == record.url


def test_a_reused_pid_is_never_signalled_or_contacted(tmp_path, monkeypatch) -> None:
    embedding_server._write_record(tmp_path, _own_record("Thu Jan  1 00:00:00 1970"))
    real_kill = os.kill

    def only_probe(pid: int, sent: int) -> None:
        if sent != 0:
            pytest.fail("signalled a foreign process")
        real_kill(pid, sent)

    monkeypatch.setattr(os, "kill", only_probe)

    assert embedding_server.running_url(tmp_path) is None
    assert embedding_server.stop(tmp_path) is False
    assert embedding_server.read_record(tmp_path) is None


def test_a_listener_without_the_launch_nonce_is_not_ready(stub, tmp_path, monkeypatch) -> None:
    stub.write_text(STUB.replace('os.environ.get("ADW_EMBEDDING_NONCE", "")', '"foreign"'), encoding="utf-8")
    monkeypatch.setattr(embedding_server, "READY_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(ValueError):
        _start(stub, tmp_path)

    assert embedding_server.read_record(tmp_path) is None


def test_a_missing_record_reads_as_absent(tmp_path) -> None:
    assert embedding_server.read_record(tmp_path) is None
    assert embedding_server.running_url(tmp_path) is None
    assert embedding_server.stop(tmp_path) is False


def test_a_failed_signal_preserves_the_record_for_a_later_cleanup(tmp_path, monkeypatch) -> None:
    record = _own_record()
    embedding_server._write_record(tmp_path, record)
    monkeypatch.setattr(embedding_server, "process_alive", lambda _pid: True)

    def denied(_pid, _signal):
        raise PermissionError("cannot signal worker")

    monkeypatch.setattr(os, "kill", denied)
    with pytest.raises(PermissionError):
        embedding_server.stop(tmp_path)

    assert embedding_server.read_record(tmp_path) == record


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
        "process_start": "Thu Jan  1 00:00:00 1970",
        "nonce": "nonce",
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


def _provisioned(entry: ModelPlatform, tmp_path: Path, runtime: str) -> tuple[str, ...]:
    return embedding_server.provision(
        entry, tmp_path,
        fetch_weights=lambda _entry, _root: tmp_path / "weights",
        fetch_runtime=lambda _entry, _root: tmp_path / runtime,
    )(4321)


def test_the_worker_command_names_the_interpreter_and_the_weights(tmp_path) -> None:
    arguments = _provisioned(ENTRY, tmp_path, "python")

    assert arguments[0] == str(tmp_path / "python")
    assert arguments[1].endswith(embedding_server.WORKER_NAME)
    assert arguments[2:] == (str(tmp_path / "weights"), "4321")


def test_the_gguf_command_points_llama_server_at_the_quantized_file(tmp_path) -> None:
    entry = Path("unused")
    from lib.model_artifacts import resolve

    arguments = _provisioned(resolve("Linux", "x86_64"), tmp_path, "llama-server")

    assert arguments[0] == str(tmp_path / "llama-server")
    assert "--embeddings" in arguments
    assert arguments[arguments.index("--port") + 1] == "4321"
    assert str(entry) not in arguments


class _Launched(Exception):
    pass


def test_the_port_is_picked_after_provisioning_finishes(tmp_path, monkeypatch) -> None:
    events = []
    embedding_client.ensure_loaded("alpha", time.time(), tmp_path / "leases", os.getpid())
    monkeypatch.setattr(embedding_client, "probe", lambda: None)

    def provision(_entry, _root) -> object:
        events.append("provision")
        return lambda port: ("python3", str(port))

    def free_port() -> int:
        events.append("port")
        return 4321

    def launch(*_args) -> None:
        events.append("launch")
        raise _Launched

    monkeypatch.setattr(embedding_server, "_free_port", free_port)
    monkeypatch.setattr(embedding_server, "_launch", launch)
    with pytest.raises(_Launched):
        embedding_server._start_leased(ENTRY, embedding_server.default_root(), provision)

    assert events == ["provision", "port", "launch"]
