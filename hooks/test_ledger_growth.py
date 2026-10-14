from __future__ import annotations

import json
from pathlib import Path

from lib import heartbeat_marks, reporting


def _heartbeats(root: Path) -> list[dict]:
    return [row for row in reporting.read_jsonl(reporting.LEDGER_FILENAME, root) if row["event"] == "observed"]


def _call(root: Path, turn_id: str, hook: str = "record") -> None:
    reporting.run_with_ledger(
        hook=hook, payload={"session_id": "s1", "turn_id": turn_id}, gate=lambda _turn: {},
        ledger_root=root / "ledger", state_root=root / "state",
    )


def test_many_calls_of_one_hook_in_one_turn_write_one_heartbeat(tmp_path: Path) -> None:
    for _ in range(5):
        _call(tmp_path, "turn-1")

    assert [(row["hook"], row["turn_id"]) for row in _heartbeats(tmp_path / "ledger")] == [("record", "turn-1")]


def test_each_turn_and_each_hook_keeps_its_heartbeat(tmp_path: Path) -> None:
    _call(tmp_path, "turn-1")
    _call(tmp_path, "turn-2")
    _call(tmp_path, "turn-2", hook="stop")

    rows = _heartbeats(tmp_path / "ledger")

    assert [(row["hook"], row["turn_id"]) for row in rows] == [("record", "turn-1"), ("record", "turn-2"), ("stop", "turn-2")]


def test_a_slow_call_always_gets_a_heartbeat(tmp_path: Path) -> None:
    _call(tmp_path, "turn-1")

    assert heartbeat_marks.worth_a_row("s1", "record", "turn-1", tmp_path / "state", heartbeat_marks.SLOW_CALL_MS)
    assert not heartbeat_marks.worth_a_row("s1", "record", "turn-1", tmp_path / "state", 0)


def test_a_full_report_keeps_the_first_findings_and_counts_the_rest(tmp_path: Path) -> None:
    findings = [{"path": "a.py", "rule": "what_comment", "line": line} for line in range(1, 251)]

    report = json.loads(Path(reporting.write_full_report(findings, {})).read_text(encoding="utf-8"))

    assert len(report) == reporting.MAX_REPORT_FINDINGS + 1
    assert report[0]["line"] == 1
    assert report[-1] == {"omitted": 50}
