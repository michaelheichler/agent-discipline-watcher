"""Because cleanup relies on process ownership, retain registrations through launch and restart."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from lib import embedding_lease, embedding_server, process_records
from lib.model_artifacts import ArchiveRuntime, Artifact, ModelPlatform, PythonRuntime
from lib.test_embedding_server import STUB


PYTHON = ModelPlatform("fixture-python", "mlx", (), PythonRuntime(()))
NATIVE = ModelPlatform("fixture-native", "gguf", (), ArchiveRuntime(
    "fixture-server", Artifact("unused", "https://example.invalid/unused", "0" * 64, 0),
))


@dataclass
class Launcher:
    script: Path
    children: list[subprocess.Popen] = field(default_factory=list)
    owners_at_spawn: list[set[str]] = field(default_factory=list)

    def prepare(self, _entry, _root) -> Callable[[int], tuple]:
        return lambda port: (sys.executable, "-I", str(self.script), str(port))

    def spawn(self, arguments, root, nonce="", *, fresh_log=False) -> subprocess.Popen:
        self.owners_at_spawn.append({row.role for row in process_records.records(root.parent)})
        child = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env={**os.environ, "ADW_EMBEDDING_NONCE": nonce})
        self.children.append(child)
        return child


@pytest.fixture
def launcher(tmp_path) -> Iterator[Launcher]:
    script = tmp_path / "http_fixture.py"
    script.write_text(STUB, encoding="utf-8")
    fake = Launcher(script)
    yield fake
    for child in fake.children:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


def wait_until(predicate) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("lifecycle fixture did not finish")


def start_and_stop(entry, root, launcher) -> tuple:
    record = embedding_server.start(entry, root, prepare=launcher.prepare, spawn=launcher.spawn)
    try:
        owners = process_records.records(root.parent)
        snapshot = [(owner.role, owner.pid, process_records.identity(owner)) for owner in owners]
    finally:
        stopped = embedding_server.stop(root)
    wait_until(lambda: not process_records.records(root.parent))
    return record, snapshot, stopped, process_records.records(root.parent)


@pytest.mark.parametrize("entry,role", [
    pytest.param(PYTHON, "embedding-worker", id="python-worker"),
    pytest.param(NATIVE, "embedding-server", id="native-server"),
])
def test_worker_launch_ownership_lasts_until_verified_process_exit(tmp_path, launcher, entry, role) -> None:
    root = tmp_path / "state/embedding-server"

    record, owners, stopped, remaining = start_and_stop(entry, root, launcher)

    assert owners == [(role, record.pid, process_records.Identity.MATCH)]
    assert stopped is True
    assert remaining == []
    assert launcher.children[0].poll() is not None


def test_a_worker_that_exits_before_readiness_leaves_no_registration(tmp_path, launcher) -> None:
    root = tmp_path / "state/embedding-server"
    launcher.script.write_text("raise SystemExit(7)\n", encoding="utf-8")

    with pytest.raises(ValueError):
        embedding_server.start(PYTHON, root, prepare=launcher.prepare, spawn=launcher.spawn)

    wait_until(lambda: not process_records.records(root.parent))
    assert process_records.records(root.parent) == []
    assert embedding_server.read_record(root) is None
    assert launcher.children[0].poll() == 7


def test_a_supervisor_launch_failure_removes_its_registration(tmp_path, launcher) -> None:
    root = tmp_path / "state/embedding-server"
    leases = tmp_path / "leases"
    embedding_lease.acquire("session", time.time(), leases, os.getpid())
    embedding_lease.register_root(root, leases)
    snapshots = []

    def failed_spawn(*_args, **_kwargs) -> subprocess.Popen:
        snapshots.append({row.role for row in process_records.records(root.parent)})
        raise OSError("fixture spawn failure")

    with pytest.raises(OSError):
        embedding_server.supervise(PYTHON, root, prepare=launcher.prepare, spawn=failed_spawn)

    assert snapshots == [{"embedding-supervisor"}]
    assert process_records.records(root.parent) == []
    assert embedding_server.read_record(root) is None


def supervise_thread(root, launcher, errors) -> None:
    try:
        embedding_server.supervise(PYTHON, root, prepare=launcher.prepare, spawn=launcher.spawn)
    except Exception as error:
        errors.append(error)


def restart_then_release(root, leases, launcher) -> tuple:
    errors = []
    thread = threading.Thread(target=supervise_thread, args=(root, launcher, errors), daemon=True)
    thread.start()
    try:
        wait_until(lambda: embedding_server.running_url(root) is not None)
        first = embedding_server.read_record(root)
        assert first is not None
        time.sleep(4 * embedding_server.READY_POLL_SECONDS)
        launcher.children[0].kill()
        wait_until(lambda: replaced_worker(root, first.pid))
        second = embedding_server.read_record(root)
        owners = {row.role for row in process_records.records(root.parent)}
    finally:
        embedding_lease.release("session", leases)
        thread.join(timeout=10)
    wait_until(lambda: not process_records.records(root.parent))
    return first, second, owners, errors, thread.is_alive()


def replaced_worker(root, old_pid) -> bool:
    record = embedding_server.read_record(root)
    return record is not None and record.pid != old_pid and embedding_server.running_url(root) is not None


def test_supervision_restarts_a_crashed_child_then_releases_all_ownership(tmp_path, launcher) -> None:
    root = tmp_path / "state/embedding-server"
    leases = tmp_path / "leases"
    embedding_lease.acquire("session", time.time(), leases, os.getpid())
    embedding_lease.register_root(root, leases)

    first, second, owners, errors, alive = restart_then_release(root, leases, launcher)

    assert first.pid != second.pid
    assert owners == {"embedding-supervisor", "embedding-worker"}
    assert launcher.owners_at_spawn == [{"embedding-supervisor"}, {"embedding-supervisor"}]
    assert errors == []
    assert alive is False
    assert process_records.records(root.parent) == []
    assert embedding_server.read_record(root) is None
