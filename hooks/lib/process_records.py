"""Keep process identities because a recycled PID must never authorize a signal."""
from __future__ import annotations

import atexit
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

try:
    from . import state_recovery
except ImportError:
    import state_recovery

try:
    from .session_state import plugin_data_home
except ImportError:
    from session_state import plugin_data_home

ROLES = frozenset({"embedding-supervisor", "embedding-server", "embedding-worker", "luna-worker"})
PS_TIMEOUT_SECONDS = 2.0
MAX_RECORD_BYTES = 8192


class Identity(StrEnum):
    """Separate uncertainty because leases and destructive cleanup need opposite defaults."""

    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Record:
    """Keep the source path because cleanup must remove only its verified record."""

    pid: int
    process_start: str | None
    role: str
    argv0: str
    adw_root: str
    path: Path
    argv: str | None = None


def _ps_start(pid: int) -> str | None:
    try:
        listed = subprocess.run(
            ("ps", "-o", "lstart=", "-p", str(pid)), capture_output=True, text=True,
            timeout=PS_TIMEOUT_SECONDS, env={**os.environ, "LC_ALL": "C"}, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return listed.stdout.strip() if listed.returncode == 0 and listed.stdout.strip() else None


def process_start(pid: int) -> str | None:
    """Pair start time with the PID because kernels reuse process numbers."""
    if type(pid) is not int or pid <= 0:
        return None
    if sys.platform != "linux":
        return _ps_start(pid)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        return f"linux:{boot}:{int(fields[19])}"
    except (OSError, ValueError, IndexError):
        return None


def process_command(pid: int) -> str | None:
    """Reject foreign users and zombies because neither authorizes cleanup."""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "uid=", "-o", "stat=", "-o", "args="],
        capture_output=True, text=True, check=False, timeout=PS_TIMEOUT_SECONDS,
    )
    if not result.stdout.strip() and result.returncode == 1:
        return None
    parts = result.stdout.strip().split(None, 2)
    if result.returncode or len(parts) != 3:
        raise RuntimeError(f"cannot verify recorded worker {pid}")
    if parts[0] != str(os.getuid()) or parts[1].startswith("Z"):
        return None
    return parts[2]


def start_times(pids: list[int]) -> dict[int, str | None]:
    """Batch each sweep because one subprocess per lease delays lifecycle callers."""
    unique = sorted({pid for pid in pids if type(pid) is int and pid > 0})
    if sys.platform == "linux":
        return {pid: process_start(pid) for pid in unique}
    found = dict.fromkeys(unique)
    if not unique:
        return found
    try:
        result = subprocess.run(
            ("ps", "-o", "pid=,lstart=", "-p", ",".join(map(str, unique))),
            capture_output=True, text=True, timeout=PS_TIMEOUT_SECONDS,
            env={**os.environ, "LC_ALL": "C"}, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return found
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and fields[0].isdigit() and int(fields[0]) in found:
                found[int(fields[0])] = fields[1]
    return found


def terminate(
    pid: int, still_ours: Callable[[], bool], *, grace: float = 3.0, poll: float = 0.05,
    alive: Callable[[int], bool] | None = None,
) -> bool:
    """Recheck ownership before each signal because PID reuse can occur during escalation."""
    signalled = False
    for termination_signal in (signal.SIGTERM, signal.SIGKILL):
        if not still_ours():
            return signalled
        try:
            os.kill(pid, termination_signal)
            signalled = True
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not (alive(pid) if alive is not None else _exists(pid)):
                return True
            time.sleep(poll)
    if not still_ours():
        return True
    raise TimeoutError(f"ADW process {pid} did not exit")


def _exists(pid: int) -> bool:
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_identity(
    pid: int, expected: object, starts: Mapping[int, str | None] | None,
    start_of: Callable[[int], str | None],
) -> Identity:
    if not isinstance(expected, str) or not expected:
        return Identity.UNKNOWN
    actual = start_of(pid) if starts is None else starts.get(pid)
    if sys.platform == "linux" and not expected.startswith("linux:") and start_of is process_start:
        actual = _ps_start(pid)
    if actual is None:
        return Identity.UNKNOWN
    return Identity.MATCH if actual == expected else Identity.MISMATCH


def _command_identity(pid: int, argv: object) -> Identity:
    if argv is None:
        return Identity.MATCH
    try:
        command = process_command(pid)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return Identity.UNKNOWN
    return Identity.MATCH if command == argv else Identity.MISMATCH


def identity(
    record: Record | Mapping[str, object], *, start_of: Callable[[int], str | None] = process_start,
    starts: Mapping[int, str | None] | None = None,
) -> Identity:
    """Keep uncertainty explicit because only a verified identity permits termination."""
    pid = record.pid if isinstance(record, Record) else record.get("pid")
    expected = record.process_start if isinstance(record, Record) else record.get("process_start")
    if os.name != "posix" or type(pid) is not int or pid <= 0:
        return Identity.UNKNOWN
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return Identity.MISMATCH
    except (OSError, OverflowError):
        return Identity.UNKNOWN
    ownership = _start_identity(pid, expected, starts, start_of)
    if ownership != Identity.MATCH:
        return ownership
    argv = record.argv if isinstance(record, Record) else record.get("argv")
    return _command_identity(pid, argv)


def is_live(record: Record | Mapping[str, object]) -> bool:
    """Require proof because callers may use this result to authorize a signal."""
    return identity(record) == Identity.MATCH


def unregister(path: str | Path) -> None:
    """Ignore a missing record because exit and cleanup may race."""
    Path(path).unlink(missing_ok=True)


def _run_directory(state_root: str | Path | None) -> Path:
    return (Path(state_root) if state_root is not None else plugin_data_home()) / "run"


def register(
    role: str, *, pid: int | None = None, state_root: str | Path | None = None,
    argv0: str | None = None,
) -> Path:
    """Record children too because native servers cannot register themselves."""
    if role not in ROLES:
        raise ValueError("unknown ADW process role")
    owner = os.getpid() if pid is None else pid
    if type(owner) is not int or owner <= 0:
        raise ValueError("invalid ADW process PID")
    directory = _run_directory(state_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{role}-{owner}.json"
    try:
        argv = process_command(owner)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        argv = None
    row = {
        "pid": owner, "process_start": process_start(owner), "role": role,
        "argv0": argv0 if argv0 is not None else sys.executable,
        "adw_root": str(Path(__file__).resolve().parents[2]),
        "argv": argv,
    }
    state_recovery.atomic_json(path, row)
    if owner == os.getpid():
        atexit.register(unregister, path)
    return path


def _valid_record_fields(row: dict) -> bool:
    valid_start = row.get("process_start") is None or isinstance(row["process_start"], str)
    valid_argv = row.get("argv") is None or (isinstance(row["argv"], str) and bool(row["argv"]))
    return all(isinstance(row.get(key), str) for key in ("argv0", "adw_root")) and valid_start and valid_argv


def _read_record(path: Path) -> Record | None:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RECORD_BYTES:
            return None
        with path.open(encoding="utf-8") as stream:
            row = json.loads(stream.read(MAX_RECORD_BYTES + 1))
    except (OSError, UnicodeError, ValueError):
        return None
    if type(row) is not dict or type(row.get("pid")) is not int or row["pid"] <= 0:
        return None
    if (
        not isinstance(row.get("role"), str) or row["role"] not in ROLES
        or path.name != f"{row['role']}-{row['pid']}.json"
    ):
        return None
    if not _valid_record_fields(row):
        return None
    return Record(
        row["pid"], row.get("process_start"), row["role"], row["argv0"], row["adw_root"], path,
        row.get("argv"),
    )


def records(state_root: str | Path | None = None) -> list[Record]:
    """Skip corrupt records because one damaged row must not hide other live workers."""
    directory = _run_directory(state_root)
    return [record for path in sorted(directory.glob("*.json")) if (record := _read_record(path)) is not None]
