from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from lib import retention, session_state


AGE = 30 * 24 * 60 * 60


def test_sweep_removes_stale_inactive_data_and_preserves_live_references(tmp_path: Path) -> None:
    now = time.time()
    data = tmp_path / "data"
    state = data / "state"
    ledger = data / "ledger"
    reports = data / "reports"
    for session_id in ("old", "live"):
        directory = state / session_id
        directory.mkdir(parents=True)
        (directory / "state.json").write_text("{}", encoding="utf-8")
        os.utime(directory, (now - AGE - 1, now - AGE - 1))
    session_state.acquire_session_lease("live", state, now)
    reports.mkdir()
    old_report = reports / "old.json"
    live_report = reports / "live.json"
    orphan = reports / "orphan.json"
    for path in (old_report, live_report, orphan):
        path.write_text("[]", encoding="utf-8")
        os.utime(path, (now - AGE - 1, now - AGE - 1))
    ledger.mkdir()
    (ledger / "ledger.jsonl").write_text(
        json.dumps({"session_id": "old", "ts": "2000-01-01T00:00:00+00:00", "report": str(old_report)})
        + "\n"
        + json.dumps({"session_id": "live", "ts": "2000-01-01T00:00:00+00:00", "report": str(live_report)})
        + "\nnot-json\n",
        encoding="utf-8",
    )
    for name in ("cache/item", "logs/item"):
        path = data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        os.utime(path, (now - AGE - 1, now - AGE - 1))

    retention.sweep(state_root=state, ledger_root=ledger, data_root=data, now=now)

    assert not (state / "old").exists()
    assert (state / "live").exists()
    assert not old_report.exists()
    assert live_report.exists()
    assert not orphan.exists()
    assert "\"live\"" in (ledger / "ledger.jsonl").read_text(encoding="utf-8")
    assert "not-json" in (ledger / "ledger.jsonl").read_text(encoding="utf-8")
    assert not (data / "cache/item").exists()
    assert not (data / "logs/item").exists()


def test_sweep_is_idempotent_and_safe_when_called_concurrently(tmp_path: Path) -> None:
    data = tmp_path / "data"
    state = data / "state"
    stale = state / "stale"
    stale.mkdir(parents=True)
    now = time.time()
    os.utime(stale, (now - AGE - 1, now - AGE - 1))

    threads = [
        threading.Thread(target=retention.sweep, kwargs={"state_root": state, "data_root": data, "now": now})
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    retention.sweep(state_root=state, data_root=data, now=now)

    assert not stale.exists()


def test_corrupt_session_lease_does_not_block_stale_cleanup(tmp_path: Path) -> None:
    state = tmp_path / "state"
    stale = state / "stale"
    stale.mkdir(parents=True)
    now = time.time()
    os.utime(stale, (now - AGE - 1, now - AGE - 1))
    leases = session_state.session_lease_root(state)
    leases.mkdir()
    (leases / "stale.lease.json").write_text("not-json", encoding="utf-8")

    retention.sweep(state_root=state, data_root=tmp_path, now=now)

    assert not stale.exists()
    assert not (leases / "stale.lease.json").exists()
