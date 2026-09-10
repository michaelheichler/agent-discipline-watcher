from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


WORKER_TERMINATE_GRACE_SECONDS = 0.2
_ENVIRONMENT_ALLOWLIST = frozenset({
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "SYSTEMROOT", "WINDIR",
})


def sdk_environment(codex_home: Path) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in _ENVIRONMENT_ALLOWLIST
    }
    environment["CODEX_HOME"] = str(codex_home)
    return environment


def child_environment(codex_home: Path, module_root: Path | None = None) -> dict[str, str]:
    environment = sdk_environment(codex_home)
    environment["PYTHONPATH"] = str(module_root or Path(__file__).parents[1])
    return environment


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    grace_deadline = time.monotonic() + WORKER_TERMINATE_GRACE_SECONDS
    if process.returncode is None:
        try:
            process.wait(timeout=WORKER_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    while process_group_exists(process.pid) and time.monotonic() < grace_deadline:
        time.sleep(0.01)
    if process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        process.wait()
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass


def process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
