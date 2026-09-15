"""Owns the model process, because a release that expects a server to already be running on the machine is not standalone."""
from __future__ import annotations

import fcntl
import ipaddress
import json
import math
import os
import signal
import socket
import subprocess
import sys
import stat
import threading
import time
import urllib.error
import urllib.request
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlsplit
from typing import NamedTuple

try:
    from .embedding_lease import has_live_leases
    from .model_artifacts import ArchiveRuntime, ModelPlatform, current_platform
    from .model_store import ensure_runtime, ensure_weights, exclusive
    from .session_state import plugin_data_home
except ImportError:
    from embedding_lease import has_live_leases
    from model_artifacts import ArchiveRuntime, ModelPlatform, current_platform
    from model_store import ensure_runtime, ensure_weights, exclusive
    from session_state import plugin_data_home

ROOT_DIRNAME = "embedding-server"
RECORD_NAME = "server.json"
LOCK_NAME = "server.lock"
SUPERVISOR_LOCK_NAME = "supervisor.lock"
LEASE_POLL_SECONDS = 5.0
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
MAX_RECORD_BYTES = 16 * 1024
MAX_RECORD_URL_CHARS = 2048
MAX_PLATFORM_CHARS = 128
MAX_PORT = 65_535
LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def default_root() -> Path:
    """One machine-wide location because the model is one process per machine, while a lease root is per test and per project."""
    return plugin_data_home() / ROOT_DIRNAME


def record_path(root: Path) -> Path:
    return root / RECORD_NAME


def _free_port() -> int:
    """Reserve a kernel-selected loopback port and return it within the valid TCP range."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    if not 1 <= port <= MAX_PORT:
        raise ValueError("allocated port is outside the valid TCP range")
    return port


class ServerRecord(NamedTuple):
    pid: int
    port: int
    url: str
    platform: str
    started_at: float


def _valid_port(value: object) -> bool:
    """Accept only a concrete TCP port in the non-reserved range."""
    return type(value) is int and 1 <= value <= MAX_PORT  # pylint: disable=unidiomatic-typecheck


def _is_loopback_host(hostname: object) -> bool:
    """Recognize literal loopback addresses without resolving attacker-controlled DNS."""
    if not isinstance(hostname, str):
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized in LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _loopback_url(url: object, *, port: int | None = None, path: str | None = None) -> bool:  # pylint: disable=too-many-return-statements
    """Require a credential-free HTTP URL on literal loopback with optional exact fields."""
    if not isinstance(url, str) or len(url) > MAX_RECORD_URL_CHARS:
        return False
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url):
        return False
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed_port = parsed.port
    except ValueError:
        return False
    if (  # pylint: disable=too-many-boolean-expressions
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed_port is None
        or not _is_loopback_host(hostname)
    ):
        return False
    if port is not None and parsed_port != port:
        return False
    return path is None or parsed.path == path


def _valid_record(record: ServerRecord) -> bool:  # pylint: disable=too-many-return-statements
    """Check every persisted field before it can influence a signal or request."""
    if not isinstance(record, ServerRecord):
        return False
    if type(record.pid) is not int or record.pid <= 0:  # pylint: disable=unidiomatic-typecheck
        return False
    if not _valid_port(record.port):
        return False
    if not _loopback_url(record.url, port=record.port, path=EMBEDDINGS_PATH):
        return False
    if (
        not isinstance(record.platform, str)
        or not record.platform
        or len(record.platform) > MAX_PLATFORM_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in record.platform)
    ):
        return False
    if type(record.started_at) not in (int, float):  # pylint: disable=unidiomatic-typecheck
        return False
    try:
        return math.isfinite(record.started_at) and record.started_at >= 0
    except (OverflowError, TypeError):
        return False
    return True


def _read_record_bytes(path: Path) -> bytes | None:
    """Read a regular record through a nonblocking no-follow descriptor and enforce its byte bound."""
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(MAX_RECORD_BYTES + 1)
    except OSError:
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > MAX_RECORD_BYTES:
        return None
    return raw


def read_record(root: Path) -> ServerRecord | None:
    """Read only a bounded, fully validated loopback server record."""
    raw = _read_record_bytes(record_path(root))
    if raw is None:
        return None
    try:
        row = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(row, dict):
        return None
    fields = {"pid", "port", "url", "platform", "started_at"}
    if set(row) != fields:
        return None
    record = ServerRecord(
        row["pid"], row["port"], row["url"], row["platform"], row["started_at"]
    )
    return record if _valid_record(record) else None


def _write_record(root: Path, record: ServerRecord) -> None:
    """Atomically persist only a valid bounded record."""
    if not _valid_record(record):
        raise ValueError("invalid embedding server record")
    raw = json.dumps(record._asdict(), separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("embedding server record exceeds the size limit")
    temporary = record_path(root).with_suffix(".tmp")
    temporary.write_bytes(raw)
    temporary.replace(record_path(root))


def discard_record(root: Path) -> None:
    record_path(root).unlink(missing_ok=True)


def process_alive(pid: int) -> bool:
    """Probe only a positive process id, reaping owned children before the signal check."""
    if type(pid) is not int or pid <= 0:  # pylint: disable=unidiomatic-typecheck
        return False
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
    """Probe only the worker's validated loopback health endpoint."""
    if not _loopback_url(url, path=HEALTH_PATH):
        return False
    try:
        with urllib.request.urlopen(url, timeout=READY_PROBE_TIMEOUT) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait_ready(health: str, child: subprocess.Popen, deadline: float) -> None:
    """Wait for a bounded loopback health probe or terminate the unready child."""
    if not _loopback_url(health, path=HEALTH_PATH):
        child.terminate()
        raise ValueError("embedding server health URL is not a loopback endpoint")
    while time.time() < deadline:
        if child.poll() is not None:
            raise ValueError(f"embedding server exited with {child.returncode} before answering {health}")
        if _answers(health):
            return
        time.sleep(READY_POLL_SECONDS)
    child.terminate()
    raise ValueError(f"embedding server did not answer {health} within {READY_TIMEOUT_SECONDS} seconds")


def _archive_command(server: Path, weights: Path, entry: ModelPlatform, port: int) -> tuple[str, ...]:
    """Build an archive-backed worker command for a validated loopback port."""
    if not _valid_port(port):
        raise ValueError("port must be between 1 and 65535")
    model = weights / entry.weights[0].name
    return (
        str(server),
        "--model",
        str(model),
        "--embeddings",
        "--port",
        str(port),
        "--host",
        "127.0.0.1",
        "--ctx-size",
        CONTEXT_TOKENS,
    )


def _python_command(interpreter: Path, weights: Path, port: int) -> tuple[str, ...]:
    """Build a Python worker command for a validated loopback port."""
    if not _valid_port(port):
        raise ValueError("port must be between 1 and 65535")
    return (str(interpreter), str(Path(__file__).parent / WORKER_NAME), str(weights), str(port))


def command(entry: ModelPlatform, root: Path, port: int) -> tuple[str, ...]:
    """Resolve artifacts only after accepting a valid loopback listen port."""
    if not _valid_port(port):
        raise ValueError("port must be between 1 and 65535")
    weights = ensure_weights(entry, root)
    runtime = ensure_runtime(entry, root)
    if isinstance(entry.runtime, ArchiveRuntime):
        return _archive_command(runtime, weights, entry, port)
    return _python_command(runtime, weights, port)


def _spawn(arguments: tuple[str, ...], root: Path) -> subprocess.Popen:
    """Starts its own session because the hook that spawns it exits within the second and must not drag the model down with it."""
    with (root / LOG_NAME).open("ab") as log:
        return subprocess.Popen(arguments, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)


def _launch(entry: ModelPlatform, root: Path, port: int, arguments: tuple[str, ...]) -> tuple[subprocess.Popen, ServerRecord]:
    """Publish ownership before readiness so Stop can terminate a worker still loading its weights."""
    child = _spawn(arguments, root)
    if type(child.pid) is not int or child.pid <= 0:  # pylint: disable=unidiomatic-typecheck
        child.terminate()
        raise ValueError("embedding server returned an invalid process id")
    record = ServerRecord(
        child.pid, port, f"http://127.0.0.1:{port}{EMBEDDINGS_PATH}", entry.key, time.time()
    )
    try:
        _write_record(root, record)
    except Exception:
        _terminate(child.pid)
        raise
    # Reap independently of the lifecycle lock, which a different hook holds while waiting for this child to exit.
    threading.Thread(target=child.wait, daemon=True).start()
    return child, record


def _ready(child: subprocess.Popen, record: ServerRecord, root: Path, *, locked: bool = False) -> None:
    try:
        _wait_ready(
            f"http://127.0.0.1:{record.port}{HEALTH_PATH}", child,
            time.time() + READY_TIMEOUT_SECONDS,
        )
    except Exception:
        with nullcontext() if locked else exclusive(root / LOCK_NAME):
            owned = read_record(root) == record
            _terminate(child.pid)
            if owned:
                discard_record(root)
        if not owned:
            return
        raise


def start(entry: ModelPlatform, root: Path) -> ServerRecord:
    """Start a worker and clean up both process and record on any readiness failure."""
    root.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    child, record = _launch(entry, root, port, command(entry, root, port))
    _ready(child, record, root, locked=True)
    return record


def _terminate(pid: int) -> bool:
    """Confirm exit even after SIGKILL, and tolerate the process exiting between probe and signal."""
    if not process_alive(pid):
        return False
    for termination_signal in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, termination_signal)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while time.monotonic() < deadline:
            if not process_alive(pid):
                return True
            time.sleep(STOP_POLL_SECONDS)
    raise TimeoutError(f"embedding server process {pid} did not exit")


def _stop(root: Path) -> bool:
    record = read_record(root)
    stopped = _terminate(record.pid) if record is not None else False
    discard_record(root)
    return stopped


def stop(root: Path, *, idle_at: float | None = None) -> bool:
    """Keep the record until exit is confirmed; serialize shutdown with startup and lease acquisition."""
    with exclusive(root / LOCK_NAME):
        if idle_at is not None and has_live_leases(root, idle_at):
            return False
        return _stop(root)


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
    """The singleton supervisor outlives hooks to unload expired leases without waiting for another turn."""
    root.mkdir(parents=True, exist_ok=True)
    _spawn((sys.executable, str(Path(__file__).resolve()), str(root)), root)


def _start_leased(entry: ModelPlatform, root: Path) -> None:
    """Provision outside the lifecycle lock, then recheck demand before launching a model after a slow download."""
    port = _free_port()
    arguments = command(entry, root, port)
    with exclusive(root / LOCK_NAME):
        if not has_live_leases(root, time.time()) or running_url(root) is not None:
            return
        child, record = _launch(entry, root, port, arguments)
    _ready(child, record, root)


def supervise(entry: ModelPlatform, root: Path) -> None:
    """Only one monitor may provision and sweep; relinquish its lock atomically with the final idle check."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / SUPERVISOR_LOCK_NAME).open("w", encoding="utf-8") as handle:
        with exclusive(root / LOCK_NAME):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        try:
            while True:
                with exclusive(root / LOCK_NAME):
                    if not has_live_leases(root, time.time()):
                        _stop(root)
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                        return
                    running = running_url(root) is not None
                if not running:
                    _start_leased(entry, root)
                time.sleep(LEASE_POLL_SECONDS)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    supervise(current_platform(), Path(sys.argv[1]))
