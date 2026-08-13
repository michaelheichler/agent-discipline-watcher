from __future__ import annotations

from pathlib import Path

import stop
from lib import reporting, session_state


def _config(root: Path) -> dict[str, str]:
    return {
        "ledger_root": str(root / "ledger"),
        "state_root": str(root / "state"),
    }


def _payload(retry: bool = False) -> dict:
    return {
        "session_id": "s1",
        "hook_event_name": "Stop",
        "last_assistant_message": "unscanned" + chr(0x2014) + "message",
        "stop_hook_active": retry,
    }


def test_stop_advances_the_turn_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert stop.run(_payload(), config) == {}
    assert session_state.read_state("s1", config["state_root"])["turn_id"] == "turn-1"


def test_stop_retry_does_not_advance_again(tmp_path: Path) -> None:
    config = _config(tmp_path)
    stop.run(_payload(), config)
    stop.run(_payload(retry=True), config)
    assert session_state.read_state("s1", config["state_root"])["turn_count"] == 1


def test_stop_records_a_heartbeat_without_scanning_chat(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert stop.run(_payload(), config) == {}
    rows = reporting._read_jsonl(reporting.LEDGER_FILENAME, config["ledger_root"])
    assert [(row["hook"], row["event"]) for row in rows] == [("stop", "observed")]
