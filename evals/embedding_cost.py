#!/usr/bin/env python3
"""Cold-starts a worker, because Task 4 needs real numbers."""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))

from lib.embedding_server import NONCE_ENV, WORKER_NAME, default_root, running_url  # pylint: disable=wrong-import-position
from lib.embedding_session import provisioned  # pylint: disable=wrong-import-position
from lib.model_artifacts import ModelPlatform, current_platform  # pylint: disable=wrong-import-position
from lib.model_store import VENV_DIRNAME, runtime_root, weights_root  # pylint: disable=wrong-import-position

OUTPUT_PATH = REPOSITORY_ROOT / "evals" / "embedding_cost.json"
COLD_CYCLES = 3
READY_TIMEOUT_SECONDS = 180.0
READY_POLL_SECONDS = 0.1
RSS_POLL_SECONDS = 0.05
STOP_GRACE_SECONDS = 10.0
STOP_POLL_SECONDS = 0.1
PROCESS_PROBE_TIMEOUT = 2.0
REQUEST_TIMEOUT_SECONDS = 60.0
KIB_PER_MIB = 1024.0
Paths = tuple[Path, Path, Path]

SENTENCES = (
    "The team reviewed the pull request before lunch.",
    "Our deployment pipeline runs every commit through automated tests.",
    "The database migration finished without any errors.",
    "She wrote a script to parse the log files.",
    "The client reported a bug in the checkout flow.",
    "We scheduled a meeting to discuss the new architecture.",
    "The server crashed twice during the load test.",
    "He refactored the authentication module last week.",
    "The design document needs one more round of feedback.",
    "Our monitoring alerts caught the outage within minutes.",
    "The intern fixed a typo in the configuration file.",
    "This release includes three new API endpoints.",
    "The support team closed forty tickets yesterday.",
    "A memory leak slowed down the background worker.",
    "The product manager asked for a status update.",
    "We rolled back the release after the failed health check.",
    "The new hire completed the onboarding checklist today.",
    "Customers noticed the improved page load time.",
    "The security audit found two minor issues.",
    "We merged the feature branch after code review.",
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline and _alive(pid):
        time.sleep(STOP_POLL_SECONDS)
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)


def _ps_field(pid: int, field: str) -> str | None:
    result = subprocess.run(
        ("ps", "-o", f"{field}=", "-p", str(pid)),
        capture_output=True, text=True, timeout=PROCESS_PROBE_TIMEOUT, check=False,
    )
    value = result.stdout.strip()
    return value or None


def _rss_kib(pid: int) -> float | None:
    field = _ps_field(pid, "rss")
    return float(field) if field is not None else None


def _cpu_seconds(pid: int) -> float | None:
    """One field, because ps already sums user and system time."""
    field = _ps_field(pid, "time")
    if field is None:
        return None
    parts = field.split(":")
    seconds = float(parts[-1])
    for index, part in enumerate(reversed(parts[:-1])):
        seconds += int(part) * (60 ** (index + 1))
    return seconds


class _RssPeak:  # pylint: disable=too-few-public-methods
    """Polls because macOS gives no push signal for peak RSS."""

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._peak_kib = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = _rss_kib(self._pid)
            if sample is not None:
                self._peak_kib = max(self._peak_kib, sample)
            self._stop.wait(RSS_POLL_SECONDS)

    def stop(self) -> float:
        self._stop.set()
        self._thread.join()
        return round(self._peak_kib / KIB_PER_MIB, 1)


def _claim(scratch_root: Path, pid: int):
    (scratch_root / "server.json").write_text(json.dumps({"pid": pid}), encoding="utf-8")
    handle = (scratch_root / "supervisor.lock").open("w", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release(handle) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def _health_body(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            status, raw = response.status, response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if status != 200:
        return None
    return json.loads(raw.decode("utf-8"))


def _health_matches(url: str, nonce: str) -> bool:
    body = _health_body(url)
    return isinstance(body, dict) and body.get("nonce") == nonce


def _wait_health(port: int, nonce: str, deadline: float) -> float:
    started = time.monotonic()
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if _health_matches(url, nonce):
            return time.monotonic() - started
        time.sleep(READY_POLL_SECONDS)
    raise TimeoutError(f"worker on port {port} never answered /health")


def _post_embeddings(port: int, sentences: tuple[str, ...]) -> float:
    payload = json.dumps({"input": list(sentences)}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/embeddings",
        data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
    elapsed = time.monotonic() - started
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or len(rows) != len(sentences):
        raise ValueError(f"expected {len(sentences)} vectors, got {rows!r}")
    return elapsed


def _paths(entry: ModelPlatform) -> Paths:
    root = default_root()
    weights = weights_root(entry, root)
    interpreter = runtime_root(entry, root) / VENV_DIRNAME / "bin" / "python"
    worker = REPOSITORY_ROOT / "hooks" / "lib" / WORKER_NAME
    return weights, interpreter, worker


def _spawn(paths: Paths, port: int, scratch_root: Path, nonce: str) -> subprocess.Popen:
    """Own root and port, because a live session must stay up."""
    weights, interpreter, worker = paths
    env = {**os.environ, NONCE_ENV: nonce}
    with (scratch_root / "worker.log").open("wb") as log:
        return subprocess.Popen(
            (str(interpreter), str(worker), str(weights), str(port), str(scratch_root)),
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=env, start_new_session=True,
        )


def _run_cycle(paths: Paths, cycle: int, base: Path) -> dict:
    """One cycle, because mixing loads would blur the numbers."""
    scratch = base / f"cycle-{cycle}"
    scratch.mkdir(parents=True)
    port = _free_port()
    nonce = secrets.token_hex(16)
    child = _spawn(paths, port, scratch, nonce)
    handle = _claim(scratch, child.pid)
    peak = _RssPeak(child.pid)
    try:
        load_s = _wait_health(port, nonce, time.monotonic() + READY_TIMEOUT_SECONDS)
        embed_s = _post_embeddings(port, SENTENCES)
        cpu_s = _cpu_seconds(child.pid)
    finally:
        peak_mb = peak.stop()
        _release(handle)
        _terminate(child.pid)
        child.wait()
    return {
        "cycle": cycle,
        "load_s": round(load_s, 3),
        "embed_s": round(embed_s, 3),
        "peak_rss_mb": peak_mb,
        "cpu_s": round(cpu_s, 3) if cpu_s is not None else None,
    }


def _run_warm(paths: Paths, base: Path) -> dict:
    """Second call, because the first pays the warmup cost."""
    scratch = base / "warm"
    scratch.mkdir(parents=True)
    port = _free_port()
    nonce = secrets.token_hex(16)
    child = _spawn(paths, port, scratch, nonce)
    handle = _claim(scratch, child.pid)
    peak = _RssPeak(child.pid)
    try:
        _wait_health(port, nonce, time.monotonic() + READY_TIMEOUT_SECONDS)
        _post_embeddings(port, SENTENCES)
        cpu_before = _cpu_seconds(child.pid)
        embed_s = _post_embeddings(port, SENTENCES)
        cpu_after = _cpu_seconds(child.pid)
    finally:
        peak_mb = peak.stop()
        _release(handle)
        _terminate(child.pid)
        child.wait()
    cpu_s = cpu_after - cpu_before if cpu_before is not None and cpu_after is not None else None
    return {
        "embed_s": round(embed_s, 3),
        "peak_rss_mb": peak_mb,
        "cpu_s": round(cpu_s, 3) if cpu_s is not None else None,
    }


def _require_provisioned() -> ModelPlatform:
    """Stops here, because downloading 709 MB is not this task."""
    if not provisioned():
        raise SystemExit("embedding weights or runtime are not provisioned, install first")
    return current_platform()


def _sysctl(name: str) -> str:
    result = subprocess.run(
        ("sysctl", "-n", name), capture_output=True, text=True,
        timeout=PROCESS_PROBE_TIMEOUT, check=False,
    )
    return result.stdout.strip()


def _machine_info() -> dict:
    memsize = _sysctl("hw.memsize")
    ram_gb = round(int(memsize) / (1024**3), 1) if memsize.isdigit() else None
    return {
        "model": _sysctl("hw.model"),
        "chip": _sysctl("machdep.cpu.brand_string"),
        "ram_gb": ram_gb,
        "date": datetime.now().date().isoformat(),
    }


def _print_table(cycles: list[dict], warm: dict) -> None:
    header = f"{'cycle':<6}{'load_s':>10}{'embed_s':>10}{'peak_rss_mb':>14}{'cpu_s':>10}"
    print(header)
    for row in cycles:
        print(f"{row['cycle']:<6}{row['load_s']:>10}{row['embed_s']:>10}{row['peak_rss_mb']:>14}{row['cpu_s']:>10}")
    print(f"{'warm':<6}{'':>10}{warm['embed_s']:>10}{warm['peak_rss_mb']:>14}{warm['cpu_s']:>10}")


def main() -> None:
    entry = _require_provisioned()
    preexisting = running_url(default_root()) is not None
    paths = _paths(entry)
    base = Path(tempfile.mkdtemp(prefix="adw-embedding-cost-"))
    try:
        cycles = [_run_cycle(paths, index, base) for index in range(1, COLD_CYCLES + 1)]
        warm = _run_warm(paths, base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    report = {
        "machine": _machine_info(),
        "platform": entry.key,
        "sentence_count": len(SENTENCES),
        "preexisting_worker": preexisting,
        "cold_cycles": cycles,
        "warm_run": warm,
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _print_table(cycles, warm)


if __name__ == "__main__":
    main()
