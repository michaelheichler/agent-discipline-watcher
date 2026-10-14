from __future__ import annotations

import os
import time
from pathlib import Path

import stop
from lib import baseline, blocker_state, scanner, stop_scan
from testing import make_repo, run_git

NARRATION = "# Increment the counter.\nx = 1\n"


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


def test_a_scope_keeps_its_newest_paths_and_counts_the_rest_once(tmp_path: Path) -> None:
    root = _config(tmp_path)["state_root"]
    paths = [str(tmp_path / f"gone{index}.py") for index in range(blocker_state.MAX_SCOPE_PATHS + 5)]
    blocker_state.touch_paths("s1", "", paths, root)

    first = _stop(tmp_path)
    second = _stop(tmp_path)

    assert "5 older edited files left the Stop rescan" in first["systemMessage"]
    assert second == {}


def test_the_cap_drops_the_pending_reason_of_a_dropped_path(tmp_path: Path) -> None:
    root = _config(tmp_path)["state_root"]
    scope = blocker_state.BlockerScope("s1", "", root)
    oldest = str(tmp_path / "old.py")
    blocker_state.apply_paths(scope, [oldest], {oldest: "Fix old.py"})

    blocker_state.apply_paths(scope, [str(tmp_path / f"n{index}.py") for index in range(blocker_state.MAX_SCOPE_PATHS)], {})

    pending, paths, _revision = blocker_state.details("s1", "", root)
    assert oldest not in paths
    assert oldest not in pending


def test_a_baseline_is_scanned_once_per_content(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    target = repo / "module.py"
    target.write_text(NARRATION, encoding="utf-8")
    run_git(repo, "add", "module.py")
    run_git(repo, "commit", "-qm", "seed")
    edited = NARRATION + "# Reset the total.\n"
    cfg = {"baseline": "report"}
    findings = scanner.scan_all(str(target), edited, cfg)
    scanned: list[str] = []
    original = baseline.scan_all
    monkeypatch.setattr(baseline, "scan_all", lambda path, text, config: scanned.append(path) or original(path, text, config))

    first = baseline.split_committed(target, findings, cfg, edited)
    second = baseline.split_committed(target, findings, cfg, edited)

    assert first == second
    assert scanned == [str(target)]


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
