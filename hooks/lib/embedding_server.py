"""Owns the model process, because a release that expects a server to already be running on the machine is not standalone."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

try:
    from .model_artifacts import ArchiveRuntime, ModelPlatform, current_platform
    from .model_store import ensure_runtime, ensure_weights, exclusive
    from .session_state import plugin_data_home
except ImportError:
    from model_artifacts import ArchiveRuntime, ModelPlatform, current_platform
    from model_store import ensure_runtime, ensure_weights, exclusive
    from session_state import plugin_data_home

ROOT_DIRNAME = "embedding-server"
RECORD_NAME = "server.json"
LOCK_NAME = "server.lock"
LOG_NAME = "server.log"
READY_TIMEOUT_SECONDS = 180.0
READY_POLL_SECONDS = 0.25
READY_PROBE_TIMEOUT = 1.0
STOP_GRACE_SECONDS = 10.0
STOP_POLL_SECONDS = 0.1
HEALTH_PATH = "/health"
EMBEDDINGS_PATH = "/v1/embeddings"
WORKER_NAME = "embedding_worker.py"
CONTEXT_TOKENS = "4096"


def default_root() -> Path:
    """One machine-wide location because the model is one process per machine, while a lease root is per test and per project."""
    return plugin_data_home() / ROOT_DIRNAME


def record_path(root: Path) -> Path:
    return root / RECORD_NAME


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class ServerRecord(NamedTuple):
    pid: int
    port: int
    url: str
    platform: str
    started_at: float


def read_record(root: Path) -> ServerRecord | None:
    try:
        row = json.loads(record_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict) or not isinstance(row.get("pid"), int):
        return None
    return ServerRecord(
        row["pid"], int(row["port"]), str(row["url"]), str(row["platform"]), float(row["started_at"])
    )


def _write_record(root: Path, record: ServerRecord) -> None:
    temporary = record_path(root).with_suffix(".tmp")
    temporary.write_text(json.dumps(record._asdict()), encoding="utf-8")
    temporary.replace(record_path(root))


def discard_record(root: Path) -> None:
    record_path(root).unlink(missing_ok=True)


def process_alive(pid: int) -> bool:
    """Reaps first because a killed child of this very process stays a zombie, and a zombie answers a signal probe as alive."""
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=READY_PROBE_TIMEOUT) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait_ready(health: str, child: subprocess.Popen, deadline: float) -> None:
    while time.time() < deadline:
        if child.poll() is not None:
            raise ValueError(f"embedding server exited with {child.returncode} before answering {health}")
        if _answers(health):
            return
        time.sleep(READY_POLL_SECONDS)
    child.terminate()
    raise ValueError(f"embedding server did not answer {health} within {READY_TIMEOUT_SECONDS} seconds")


def _archive_command(server: Path, weights: Path, entry: ModelPlatform, port: int) -> tuple[str, ...]:
    model = weights / entry.weights[0].name
    return (str(server), "--model", str(model), "--embeddings", "--port", str(port),
            "--host", "127.0.0.1", "--ctx-size", CONTEXT_TOKENS)


def _python_command(interpreter: Path, weights: Path, port: int) -> tuple[str, ...]:
    return (str(interpreter), str(Path(__file__).parent / WORKER_NAME), str(weights), str(port))


def command(entry: ModelPlatform, root: Path, port: int) -> tuple[str, ...]:
    weights = ensure_weights(entry, root)
    runtime = ensure_runtime(entry, root)
    if isinstance(entry.runtime, ArchiveRuntime):
        return _archive_command(runtime, weights, entry, port)
    return _python_command(runtime, weights, port)


def _spawn(arguments: tuple[str, ...], root: Path) -> subprocess.Popen:
    """Starts its own session because the hook that spawns it exits within the second and must not drag the model down with it."""
    log = (root / LOG_NAME).open("ab")
    return subprocess.Popen(arguments, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)


def start(entry: ModelPlatform, root: Path) -> ServerRecord:
    root.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    child = _spawn(command(entry, root, port), root)
    health = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    _wait_ready(health, child, time.time() + READY_TIMEOUT_SECONDS)
    record = ServerRecord(
        child.pid, port, f"http://127.0.0.1:{port}{EMBEDDINGS_PATH}", entry.key, time.time()
    )
    _write_record(root, record)
    return record


def stop(root: Path) -> bool:
    """Waits on the pid rather than posting to a route, because unload has to mean the process is gone."""
    record = read_record(root)
    discard_record(root)
    if record is None or not process_alive(record.pid):
        return False
    os.kill(record.pid, signal.SIGTERM)
    deadline = time.time() + STOP_GRACE_SECONDS
    while time.time() < deadline and process_alive(record.pid):
        time.sleep(STOP_POLL_SECONDS)
    if process_alive(record.pid):
        os.kill(record.pid, signal.SIGKILL)
    return True


def running_url(root: Path) -> str | None:
    record = read_record(root)
    if record is None or not process_alive(record.pid):
        return None
    return record.url


def ensure_running(entry: ModelPlatform, root: Path) -> str:
    """Sweeps a record whose process is gone, because a crashed server has to be respawned rather than reported absent forever."""
    root.mkdir(parents=True, exist_ok=True)
    with exclusive(root / LOCK_NAME):
        url = running_url(root)
        if url is not None:
            return url
        discard_record(root)
        return start(entry, root).url


def start_detached(root: Path) -> None:
    """Detached because provisioning downloads most of a gigabyte and the prompt that triggers it must not wait."""
    root.mkdir(parents=True, exist_ok=True)
    log = (root / LOG_NAME).open("ab")
    subprocess.Popen(
        (sys.executable, str(Path(__file__).resolve()), str(root)),
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )


if __name__ == "__main__":
    ensure_running(current_platform(), Path(sys.argv[1]))
