"""Because uninstall removes runtimes, stop only identity-verified ADW processes first."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
import os
from pathlib import Path
import re

from . import adw_copies, embedding_server, process_records
from .config_roots import data_root
from .update_runtime import check_path


@dataclass(frozen=True, slots=True)
class Worker:
    """Because the kernel reuses PIDs, pin each worker's start identity."""

    record: process_records.Record
    command: str


def _adw_script(prefix: str) -> bool:
    scripts = (Path(prefix[start.start(1):]) for start in re.finditer(r"(?:^|\s)(/)", prefix))
    return any(len(script.parents) >= 3 and adw_copies.is_adw(script.parents[2]) for script in scripts)


def _worker_command(command: str, role: str, home: Path) -> bool:
    names = {"server": "embedding_worker.py", "supervisor": "embedding_server.py", "luna": "luna_worker.py"}
    suffix = re.escape("/hooks/lib/" + names[role])
    for match in re.finditer(suffix + r"(?=\s|$)", command):
        if _adw_script(command[:match.end()]):
            return True
    return (role == "server" and str(data_root(home)) + "/" in command
            and re.search(r"/llama-server(?:\s|$)", command) is not None
            and re.search(r"(?:^|\s)--embeddings(?:\s|$)", command) is not None)


def _recorded_worker(record: process_records.Record, home: Path) -> Worker | None:
    check_path(record.path, home)
    if record.pid <= 1:
        raise RuntimeError(f"cannot verify worker record: {record.path}")
    ownership = process_records.identity(record)
    if ownership == process_records.Identity.MISMATCH:
        return None
    if ownership == process_records.Identity.UNKNOWN:
        raise RuntimeError(f"cannot verify worker identity: {record.path}")
    command = record.argv or process_records.process_command(record.pid)
    if command is None:
        return None
    if record.argv is not None:
        if not adw_copies.is_adw(Path(record.adw_root)):
            return None
    else:
        role = "luna" if record.role == "luna-worker" else record.role.removeprefix("embedding-")
        role = "server" if role == "worker" else role
        module_worker = (role == "luna" and re.search(r"(?:^|\s)-m\s+lib\.luna_worker(?:\s|$)", command)
                         and adw_copies.is_adw(Path(record.adw_root)))
        if not _worker_command(command, role, home) and not module_worker:
            return None
    return Worker(record, command)


def workers(home: Path) -> list[Worker]:
    """Because old installs lack registrations, retain one server-record fallback."""
    state = data_root(home)
    check_path(state / "run", home)
    registered = process_records.records(state)
    known = {row.path for row in registered}
    for path in (state / "run").glob("*.json"):
        if path not in known and any(path.name.startswith(role + "-") for role in process_records.ROLES):
            raise RuntimeError(f"cannot verify recorded ADW process: {path}")
    registered.sort(key=lambda record: record.role != "embedding-supervisor")
    legacy_path = embedding_server.record_path(state / embedding_server.ROOT_DIRNAME)
    if os.path.lexists(legacy_path):
        check_path(legacy_path, home)
        legacy = embedding_server.read_record(legacy_path.parent)
        if legacy is None:
            raise RuntimeError(f"cannot verify worker record: {legacy_path}")
        if legacy.pid not in {record.pid for record in registered}:
            registered.append(process_records.Record(
                legacy.pid, legacy.process_start, "embedding-server", "", "", legacy_path,
            ))
    found = [_recorded_worker(record, home) for record in registered]
    return list({worker.record.pid: worker for worker in found if worker is not None}.values())


def _same_worker(
    worker: Worker, *, start_of: Callable[[int], str | None] = process_records.process_start,
) -> bool:
    ownership = process_records.identity(worker.record, start_of=start_of)
    if ownership == process_records.Identity.MISMATCH:
        if (worker.record.argv is not None
                and process_records.identity(replace(worker.record, argv=None), start_of=start_of) == process_records.Identity.MATCH):
            raise RuntimeError(f"ADW worker {worker.record.pid} changed command; retained runtime files")
        return False
    if ownership == process_records.Identity.UNKNOWN:
        raise RuntimeError(f"cannot verify ADW worker {worker.record.pid}; retained runtime files")
    if worker.record.argv is not None:
        return True
    command = process_records.process_command(worker.record.pid)
    if command is None:
        return False
    if command != worker.command:
        raise RuntimeError(f"ADW worker {worker.record.pid} changed command; retained runtime files")
    return True


def stop_worker(
    worker: Worker, *, start_of: Callable[[int], str | None] = process_records.process_start,
) -> None:
    """Because PIDs can change owners, recheck identity before each signal."""
    try:
        stopped = process_records.terminate(worker.record.pid, partial(_same_worker, worker, start_of=start_of))
    except TimeoutError as exc:
        raise RuntimeError(f"ADW worker {worker.record.pid} did not stop; retained runtime files") from exc
    if stopped:
        print(f"stopped ADW worker {worker.record.pid}")
