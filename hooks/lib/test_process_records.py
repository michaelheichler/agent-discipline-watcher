"""Verify process ownership because uncertain PIDs must never authorize termination."""
from __future__ import annotations

from dataclasses import replace
import json
import signal
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from lib import process_records


def test_registered_processes_are_discoverable_with_verified_ownership(tmp_path) -> None:
    path = process_records.register("embedding-supervisor", state_root=tmp_path)

    [record] = process_records.records(tmp_path)

    assert record.path == path
    assert record.pid == os.getpid()
    assert record.process_start
    assert process_records.identity(record) == process_records.Identity.MATCH
    assert process_records.is_live(record) is True


def test_removing_a_record_twice_leaves_no_discoverable_process(tmp_path) -> None:
    path = process_records.register("embedding-supervisor", state_root=tmp_path)

    remove_twice(path)

    assert process_records.records(tmp_path) == []


def remove_twice(path) -> None:
    process_records.unregister(path)
    process_records.unregister(path)


@pytest.mark.parametrize("token,expected", [
    pytest.param(None, "UNKNOWN", id="missing"),
    pytest.param("", "UNKNOWN", id="empty"),
    pytest.param("previous-process-start", "MISMATCH", id="recycled-pid"),
])
def test_unverified_processes_never_authorize_a_signal(token, expected) -> None:
    record = {"pid": os.getpid(), "process_start": token}

    identity = process_records.identity(record)

    assert identity == process_records.Identity[expected]
    assert process_records.is_live(record) is False


def test_a_confirmed_exited_child_is_not_a_live_owner() -> None:
    child = subprocess.run([sys.executable, "-I", "-c", "import os; print(os.getpid())"],
                           check=True, capture_output=True, text=True)
    record = {"pid": int(child.stdout.strip()), "process_start": "exited-child"}

    identity = process_records.identity(record)

    assert identity == process_records.Identity.MISMATCH
    assert process_records.is_live(record) is False


@pytest.mark.parametrize("kind", [
    pytest.param("malformed", id="malformed-json"),
    pytest.param("role", id="list-valued-role"),
    pytest.param("pid", id="invalid-pid"),
    pytest.param("oversized", id="oversized-record"),
    pytest.param("symlink", id="symlink"),
    pytest.param("fifo", id="fifo"),
])
def test_invalid_record_files_cannot_hide_a_valid_registration(tmp_path, kind) -> None:
    valid = process_records.register("embedding-supervisor", state_root=tmp_path)
    invalid_record(tmp_path, kind)

    records = process_records.records(tmp_path)

    assert [record.path for record in records] == [valid]


def invalid_record(root: Path, kind: str) -> None:
    row = {"pid": os.getpid(), "process_start": None, "role": "embedding-worker",
           "argv0": sys.executable, "adw_root": str(root)}
    path = root / "run" / f"embedding-worker-{os.getpid()}.json"
    if kind == "fifo":
        os.mkfifo(path)
        return
    if kind == "symlink":
        outside = root / "outside.json"
        outside.write_text(json.dumps(row), encoding="utf-8")
        path.symlink_to(outside)
        return
    if kind == "role":
        row["role"] = ["embedding-worker"]
    if kind == "pid":
        row["pid"] = -1
    text = json.dumps(row)
    if kind == "malformed":
        text = "{"
    if kind == "oversized":
        text += " " * (process_records.MAX_RECORD_BYTES + 1)
    path.write_text(text, encoding="utf-8")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS process identity contract")
def test_macos_start_identity_ignores_the_callers_locale(monkeypatch) -> None:
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    listed = subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())],
                            check=True, capture_output=True, text=True,
                            env={**os.environ, "LC_ALL": "C"})

    token = process_records.process_start(os.getpid())

    assert token == listed.stdout.strip()
    assert process_records.identity({"pid": os.getpid(), "process_start": token}) \
        == process_records.Identity.MATCH


@pytest.mark.skipif(sys.platform != "linux", reason="Linux proc identity contract")
def test_linux_start_identity_handles_parentheses_in_the_process_name() -> None:
    script = (
        "import ctypes, os, sys; "
        "ctypes.CDLL(None).prctl(15, b'owner) name)'); "
        "print(os.getpid(), flush=True); sys.stdin.read()"
    )
    with subprocess.Popen([sys.executable, "-I", "-c", script], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as child:
        try:
            pid = int(child.stdout.readline())
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            fields = re.fullmatch(r"\d+ \(.*\) \S (.*)", stat.strip())
            tick = fields.group(1).split()[18]
            boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()

            token = process_records.process_start(pid)

            assert token == f"linux:{boot}:{tick}"
        finally:
            child.terminate()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="Legacy Linux ps identity contract")
def test_linux_identity_keeps_legacy_ps_start_tokens_verifiable() -> None:
    listed = subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())],
                            check=True, capture_output=True, text=True,
                            env={**os.environ, "LC_ALL": "C"})
    record = {"pid": os.getpid(), "process_start": listed.stdout.strip()}

    identity = process_records.identity(record)

    assert identity == process_records.Identity.MATCH


def test_process_termination_rechecks_ownership_before_escalation(monkeypatch) -> None:
    ownership = iter((True, False))
    signals = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))

    result = process_records.terminate(
        12345, lambda: next(ownership), grace=0, alive=lambda _pid: True,
    )

    assert result is True
    assert signals == [(12345, signal.SIGTERM)]


@pytest.mark.parametrize("changed", [pytest.param(False, id="matching-command"), pytest.param(True, id="changed-command")])
def test_registered_command_identity_rejects_changed_arguments(tmp_path, changed) -> None:
    process_records.register("embedding-worker", state_root=tmp_path)
    [record] = process_records.records(tmp_path)
    candidate = replace(record, argv=record.argv + " changed" * changed)

    result = process_records.identity(candidate)

    assert record.argv
    assert result == (process_records.Identity.MISMATCH if changed else process_records.Identity.MATCH)
