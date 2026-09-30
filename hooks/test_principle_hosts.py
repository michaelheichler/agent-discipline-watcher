"""Pin the session wiring, because unit tests hand it in."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

import pytest

import pre_tool
import record
import stop
from lib import blocker_state, finding_output, principle_kb

RULE = "assert_in_loop"
LOOP_TEST = "def test_every_case() -> None:\n    for value in (1, 2, 3):\n        assert value > 0\n"


def _store(root: Path) -> str:
    entry_id = finding_output.principle_map()[RULE]
    root.mkdir(parents=True)
    connection = sqlite3.connect(root / principle_kb.DB_NAME)
    connection.execute("CREATE TABLE principle (source TEXT, entry_id TEXT, title TEXT, text TEXT)")
    connection.execute(
        "INSERT INTO principle VALUES ('deviq', ?, 'Loops', 'One case per test keeps a failure visible.')",
        (entry_id,),
    )
    connection.commit()
    connection.close()
    row = principle_kb.entry(entry_id, root=root)
    assert row is not None
    return row.text


def _config(root: Path) -> dict[str, str]:
    return {
        "state_root": str(root / "state"),
        "ledger_root": str(root / "ledger"),
        "principle_root": str(root / "cache"),
    }


def _payload(cwd: Path, tool_name: str, tool_input: dict, call: str) -> dict:
    return {
        "session_id": "s1", "hook_event_name": "PreToolUse", "cwd": str(cwd),
        "tool_name": tool_name, "tool_use_id": call, "tool_input": tool_input,
    }


def _claude_write(cwd: Path, name: str, config: dict) -> str:
    target = str(cwd / name)
    response = pre_tool.run(_payload(cwd, "Write", {"file_path": target, "content": LOOP_TEST}, name), config)
    return response["reason"]


def _codex_patch(cwd: Path, name: str, config: dict) -> str:
    body = "".join(f"+{line}\n" for line in LOOP_TEST.splitlines())
    patch = f"*** Begin Patch\n*** Add File: {name}\n{body}*** End Patch\n"
    response = pre_tool.run(_payload(cwd, "apply_patch", {"command": ["apply_patch", patch]}, name), config)
    return response["reason"]


def _post_tool_use(cwd: Path, name: str, config: dict) -> str:
    (cwd / name).write_text(LOOP_TEST, encoding="utf-8")
    payload = {**_payload(cwd, "Write", {"file_path": str(cwd / name)}, name), "hook_event_name": "PostToolUse"}
    return record.run(payload, config, renew=lambda _session, _root: True)["reason"]


def _stop(cwd: Path, name: str, config: dict) -> str:
    (cwd / name).write_text(LOOP_TEST, encoding="utf-8")
    blocker_state.touch_paths("s1", "", [str(cwd / name)], config["state_root"])
    payload = {"session_id": "s1", "hook_event_name": "Stop", "cwd": str(cwd), "stop_hook_active": False}
    return stop.run(payload, config)["reason"]


@pytest.mark.parametrize("render", [_claude_write, _codex_patch, _post_tool_use, _stop])
def test_hook_explains_the_rule_once_per_session(tmp_path: Path, render: Callable[[Path, str, dict], str]) -> None:
    text = _store(tmp_path / "cache")
    config = _config(tmp_path)

    first = render(tmp_path, "test_first.py", config)
    second = render(tmp_path, "test_second.py", config)

    assert (RULE in first, text in first, RULE in second, text in second) == (True, True, True, False)
