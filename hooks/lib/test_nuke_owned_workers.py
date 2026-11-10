"""Verify uninstall ordering because runtime deletion must not strand verified workers."""
from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from lib import embedding_server, nuke_runtime, process_records


WORKER = '''import os
import pathlib
import signal
import sys

runtime = pathlib.Path(sys.argv[-2])
witness = pathlib.Path(sys.argv[-1])

def stopped(_signal, _frame) -> None:
    witness.write_text(str(runtime.exists()), encoding="utf-8")
    raise SystemExit(0)

def changed(_signal, _frame) -> None:
    code = "import signal; print('changed', flush=True); signal.pause()"
    os.execv(sys.executable, [sys.executable, "-I", "-c", code])

signal.signal(signal.SIGTERM, stopped)
signal.signal(signal.SIGUSR1, changed)
print("ready", flush=True)
while True:
    signal.pause()
'''


def steps(home) -> nuke_runtime.NukeSteps:
    return nuke_runtime.NukeSteps(account_home=lambda: home, environment=lambda: {"PATH": ""})


def child_record(runtime, role, pid) -> Path:
    listed = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                            check=True, capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    path = runtime / "run" / f"{role}-{pid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "process_start": listed.stdout.strip(),
                               "role": role, "argv0": sys.executable,
                               "adw_root": str(runtime.parent.parent / "checkout")}),
                    encoding="utf-8")
    return path


def worker_arguments(root, role) -> tuple:
    home = root / "home"
    runtime = home / ".adw"
    runtime.mkdir(parents=True)
    checkout = root / "checkout"
    manifest = checkout / ".claude-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "agent-discipline-watcher"}), encoding="utf-8")
    names = {"embedding-worker": "embedding_worker.py", "embedding-supervisor": "embedding_server.py",
             "luna-worker": "luna_worker.py", "luna-module": "luna_worker.py",
             "native": "llama-server", "foreign": "outside.py"}
    script = checkout / "hooks/lib" / names[role]
    if role == "native":
        script = runtime / "runtime/bin/llama-server"
    if role == "luna-module":
        script = checkout / "lib/luna_worker.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(WORKER, encoding="utf-8")
    witness = root / "stopped-with-runtime"
    arguments = [sys.executable, "-I", str(script)]
    if role == "luna-module":
        arguments = [sys.executable, "-S", "-m", "lib.luna_worker"]
    if role == "native":
        arguments.append("--embeddings")
    return home, runtime, witness, arguments + [str(runtime), str(witness)]


@pytest.fixture
def live_worker(tmp_path, request) -> Iterator[tuple]:
    role = request.param
    home, runtime, witness, arguments = worker_arguments(tmp_path, role)
    child = subprocess.Popen(arguments, cwd=tmp_path / "checkout", stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        aliases = {"native": "embedding-server", "foreign": "embedding-worker",
                   "luna-module": "luna-worker"}
        recorded_role = aliases.get(role, role)
        registration = child_record(runtime, recorded_role, child.pid)
        yield home, child, witness, registration
    finally:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)


@pytest.mark.parametrize("live_worker", [
    "embedding-worker", "embedding-supervisor", "luna-worker", "luna-module", "native",
], indirect=True)
def test_uninstall_stops_verified_workers_before_removing_the_runtime(live_worker) -> None:
    home, child, witness, _registration = live_worker

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 0
    assert witness.exists()
    assert child.wait(timeout=5) == 0
    assert witness.read_text(encoding="utf-8") == "True"
    assert not (home / ".adw").exists()


@pytest.mark.parametrize("live_worker", ["foreign"], indirect=True)
def test_uninstall_does_not_signal_a_foreign_command_with_a_valid_pid_record(live_worker) -> None:
    home, child, witness, _registration = live_worker

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 0
    assert child.poll() is None
    assert not witness.exists()


@pytest.mark.parametrize("live_worker", ["embedding-worker"], indirect=True)
@pytest.mark.parametrize("token,outcome", [
    pytest.param(None, (2, True), id="unknown"),
    pytest.param("previous-process-start", (0, False), id="recycled-pid"),
])
def test_unverified_process_identity_never_authorizes_signals(live_worker, token, outcome) -> None:
    home, child, witness, registration = live_worker
    expected, retained = outcome
    row = json.loads(registration.read_text(encoding="utf-8"))
    row["process_start"] = token
    registration.write_text(json.dumps(row), encoding="utf-8")

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == expected
    assert child.poll() is None
    assert not witness.exists()
    assert (home / ".adw").exists() is retained


@pytest.mark.parametrize("live_worker", ["embedding-worker"], indirect=True)
def test_a_command_change_after_planning_preserves_the_runtime(live_worker) -> None:
    home, child, witness, _registration = live_worker
    plan = nuke_runtime.build_plan(home, steps(home))
    child.send_signal(signal.SIGUSR1)
    assert child.stdout.readline().strip() == "changed"

    with pytest.raises(RuntimeError):
        nuke_runtime.execute(plan, home, steps(home))

    assert child.poll() is None
    assert not witness.exists()
    assert (home / ".adw").exists()


def test_a_corrupt_process_registration_prevents_destructive_uninstall(tmp_path) -> None:
    home = tmp_path / "home"
    path = home / ".adw/run/embedding-worker-123.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")

    result = nuke_runtime.main(["--yes"], steps=steps(home))

    assert result == 2
    assert path.read_text(encoding="utf-8") == "{"


@pytest.mark.parametrize("live_worker", ["embedding-worker"], indirect=True)
def test_legacy_server_record_cannot_replace_a_registered_command_identity(live_worker) -> None:
    home, child, witness, _registration = live_worker
    state = home / ".adw"
    process_records.register("embedding-worker", pid=child.pid, state_root=state)
    [record] = process_records.records(state)
    legacy = embedding_server.record_path(state / embedding_server.ROOT_DIRNAME)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({
        "pid": child.pid, "port": 1234, "url": "http://127.0.0.1:1234/v1/embeddings",
        "platform": "stub", "started_at": 5.0, "process_start": record.process_start, "nonce": "nonce",
    }), encoding="utf-8")
    plan = nuke_runtime.build_plan(home, steps(home))
    child.send_signal(signal.SIGUSR1)
    assert child.stdout.readline().strip() == "changed"

    with pytest.raises(RuntimeError):
        nuke_runtime.execute(plan, home, steps(home))

    assert child.poll() is None
    assert not witness.exists()
    assert state.exists()
