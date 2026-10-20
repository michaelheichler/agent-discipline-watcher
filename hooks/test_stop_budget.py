from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

import stop
from lib import baseline, blocker_state, imported_baseline, state_recovery, stop_scan
from testing import make_repo, run_git

NARRATION = "# Increment the counter.\nx = 1\n"
EDITED = NARRATION + "# Reset the total.\n"
BUDGET_SECONDS = 0.3
DEADLINE_MARGIN_SECONDS = 0.5
LARGE_BASELINE_BYTES = 3_000_000
OVERSIZED_CURRENT_BYTES = 9_900_000
RAISED_SCAN_BYTES = 20_000_000
BUSY_SCAN_SECONDS = 3.0
SLOW_RECOVERY_SECONDS = 0.5
BUSY_CURRENT_SCAN_SECONDS = 0.2
OUTER_ALARM_SECONDS = 0.05
OUTER_ALARM_SLACK_SECONDS = 0.05
LARGE_PROSE = "The hook reads the file. It scans each line and records what it finds for the agent.\n\n"
DASHED_LINE = "The scan ends here — and the agent sees it.\n"


def _config(root: Path) -> dict[str, str]:
    return {"ledger_root": str(root / "ledger"), "state_root": str(root / "state")}


def _stop(tmp_path: Path) -> dict:
    return stop.run({"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "Stop"}, _config(tmp_path))


def test_a_rescan_past_its_deadline_blocks_with_the_unscanned_count(tmp_path: Path, monkeypatch) -> None:
    paths = []
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
        paths.append(str(tmp_path / name))
    blocker_state.touch_paths("s1", "", paths, _config(tmp_path)["state_root"])
    monkeypatch.setattr(stop_scan, "STOP_SCAN_SECONDS", -1.0)

    response = _stop(tmp_path)

    assert response["decision"] == "block"
    assert "2 files not scanned: a.py, b.py" in response["reason"]
    assert blocker_state.details("s1", "", _config(tmp_path)["state_root"])[1] == paths


def test_a_slow_baseline_git_call_ends_at_the_deadline_as_unscanned(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    hanging = tmp_path / "bin" / "git"
    hanging.parent.mkdir()
    hanging.write_text("#!/bin/sh\nexec sleep 5\n", encoding="utf-8")
    hanging.chmod(0o755)
    monkeypatch.setenv("PATH", f"{hanging.parent}{os.pathsep}{os.environ['PATH']}")
    started = time.monotonic()

    scanned = stop_scan.rescan([str(target)], tmp_path, {}, started + 0.5)

    assert scanned.skipped == [str(target)]
    assert scanned.findings == []
    assert time.monotonic() - started < 1.5


def test_an_edit_to_an_unscanned_file_blocks_again_after_a_release(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    blocker_state.touch_paths("s1", "", [str(target)], _config(tmp_path)["state_root"])
    monkeypatch.setattr(stop_scan, "STOP_SCAN_SECONDS", -1.0)
    assert "decision" not in [_stop(tmp_path) for _ in range(3)][2]

    target.write_text("x = 2\ny = 3\n", encoding="utf-8")

    assert _stop(tmp_path)["decision"] == "block"


def test_a_duplicate_check_cut_off_by_the_deadline_keeps_the_batch_block(tmp_path: Path, monkeypatch) -> None:
    root = _config(tmp_path)["state_root"]
    paths = []
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
        paths.append(str(tmp_path / name))
    blocker_state.touch_paths("s1", "", paths, root)
    blocker_state.set_pending("s1", "", "<batch>", "Duplicate content", root)
    full = stop_scan.rescan
    monkeypatch.setattr(stop_scan, "rescan", lambda found, cwd, cfg, _until: full(found, cwd, cfg, float("inf")))
    monkeypatch.setattr(stop_scan, "deadline", lambda: 0.0)

    response = _stop(tmp_path)

    assert response["decision"] == "block"
    assert "before the duplicate content check" in response["reason"]
    assert "<batch>" in blocker_state.details("s1", "", root)[0]


class Edited(NamedTuple):
    target: Path
    cwd: Path
    cfg: dict


def _imported_edit(tmp_path: Path) -> Edited:
    target = tmp_path / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    cfg = {"session_id": "s1", "state_root": str(tmp_path / "state")}
    imported_baseline.snapshot_many("s1", [str(target)], cfg["state_root"])
    target.write_text(EDITED, encoding="utf-8")
    return Edited(target, tmp_path, cfg)


def _committed_edit(tmp_path: Path) -> Edited:
    repo = make_repo(tmp_path)
    target = repo / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    run_git(repo, "add", "module.py")
    run_git(repo, "commit", "-qm", "seed")
    target.write_text(EDITED, encoding="utf-8")
    return Edited(target, repo, {})


def _stall(monkeypatch, module: object, name: str) -> None:
    original = getattr(module, name)

    def busy(*args: object) -> object:
        ends = time.monotonic() + BUSY_SCAN_SECONDS
        while time.monotonic() < ends:
            pass
        return original(*args)

    monkeypatch.setattr(module, name, busy)


class Stall(NamedTuple):
    module: object
    name: str
    arrange: Callable[[Path], Edited]


@pytest.mark.parametrize("stall", [
    pytest.param(Stall(stop_scan, "scan_all", _imported_edit), id="scan-of-the-current-file"),
    pytest.param(Stall(baseline, "compare_any", _imported_edit), id="diff-against-an-imported-baseline"),
    pytest.param(Stall(baseline, "compare_any", _committed_edit), id="diff-against-the-committed-baseline"),
])
def test_a_stalled_rescan_step_ends_at_the_deadline_as_unscanned(tmp_path: Path, monkeypatch, stall: Stall) -> None:
    edited = stall.arrange(tmp_path)
    _stall(monkeypatch, stall.module, stall.name)
    started = time.monotonic()

    scanned = stop_scan.rescan([str(edited.target)], edited.cwd, edited.cfg, started + BUDGET_SECONDS)

    assert (scanned.skipped, scanned.existing) == ([str(edited.target)], [])
    assert time.monotonic() - started < BUDGET_SECONDS + DEADLINE_MARGIN_SECONDS


def test_a_large_imported_baseline_finishes_inside_the_stop_budget(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text(LARGE_PROSE * (LARGE_BASELINE_BYTES // len(LARGE_PROSE)), encoding="utf-8")
    cfg = {"session_id": "s1", "state_root": str(tmp_path / "state")}
    imported_baseline.snapshot_many("s1", [str(target)], cfg["state_root"])
    target.write_text(DASHED_LINE, encoding="utf-8")

    scanned = stop_scan.rescan([str(target)], tmp_path, cfg, stop_scan.deadline())

    assert scanned.skipped == []
    assert [(row["line"], row["rule"]) for row in scanned.findings] == [(1, "banned_dash")]


def test_an_oversized_current_file_ends_at_the_deadline_as_unscanned(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text(LARGE_PROSE * (OVERSIZED_CURRENT_BYTES // len(LARGE_PROSE)), encoding="utf-8")
    started = time.monotonic()

    scanned = stop_scan.rescan([str(target)], tmp_path, {"max_scan_bytes": RAISED_SCAN_BYTES}, started + BUDGET_SECONDS)

    assert scanned.skipped == [str(target)]
    assert time.monotonic() - started < BUDGET_SECONDS + DEADLINE_MARGIN_SECONDS


def test_a_deadline_during_a_slow_state_recovery_lets_the_restore_finish(tmp_path: Path, monkeypatch) -> None:
    root = _config(tmp_path)["state_root"]
    target = tmp_path / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    blocker_state.set_pending("s1", "", str(target), "Fix module.py", root)
    state_file = Path(root) / "s1" / "state.json"
    state_file.write_text("{", encoding="utf-8")
    write = state_recovery.atomic_write

    def slow_write(path: Path, payload: str) -> None:
        time.sleep(SLOW_RECOVERY_SECONDS)
        write(path, payload)

    monkeypatch.setattr(state_recovery, "atomic_write", slow_write)

    stop_scan.rescan([str(target)], tmp_path, {"session_id": "s1", "state_root": root}, time.monotonic() + BUDGET_SECONDS)

    assert "Fix module.py" in state_file.read_text(encoding="utf-8")


def test_an_earlier_outer_alarm_fires_on_time_during_a_rescan(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    original = stop_scan.scan_all

    def busy(path: str, text: str, config: dict) -> list[dict]:
        ends = time.monotonic() + BUSY_CURRENT_SCAN_SECONDS
        while time.monotonic() < ends:
            pass
        return original(path, text, config)

    monkeypatch.setattr(stop_scan, "scan_all", busy)
    fired: list[float] = []
    previous = signal.signal(signal.SIGALRM, lambda _signum, _frame: fired.append(time.monotonic()))
    started = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, OUTER_ALARM_SECONDS)
    try:
        scanned = stop_scan.rescan([str(target)], tmp_path, {}, started + BUDGET_SECONDS)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    assert scanned.skipped == []
    assert fired[0] - started < OUTER_ALARM_SECONDS + OUTER_ALARM_SLACK_SECONDS


def test_a_finished_rescan_leaves_no_alarm_armed(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    handler = signal.getsignal(signal.SIGALRM)

    stop_scan.rescan([str(target)], tmp_path, {}, time.monotonic() + BUDGET_SECONDS)

    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) is handler
