from __future__ import annotations

import json
import re
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


def _spread(count: int, paths: int) -> list[dict]:
    return [
        {"path": f"module_{index * paths // count}.py", "family": "clean_code", "rule": "what_comment",
         "line": index + 1, "action": "fix", "snippet": f"line {index}"}
        for index in range(count)
    ]


def test_the_linked_full_report_keeps_every_finding_on_every_path() -> None:
    _message, report = reporting.compact_block(_spread(1681, 117), {})

    saved = [row for row in json.loads(Path(report).read_text(encoding="utf-8")) if "rule" in row]

    assert (len(saved), len({row["path"] for row in saved})) == (1681, 117)


def test_the_compact_response_stays_bounded_and_accounts_for_every_finding() -> None:
    message, _report = reporting.compact_block(_spread(1681, 117), {}, report_path="report.json")

    lines = message.splitlines()
    listed = sum("module_" in line for line in lines)
    remainder = int(re.match(r"\d+", lines[-1]).group())
    assert len(message.encode("utf-8")) <= reporting.MAX_COMPACT_BYTES
    assert listed + remainder == 1681
