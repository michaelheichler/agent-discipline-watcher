"""Because a sink device and a deleted file hold no content, only a target that may still hide text owes an unscannable_file row."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import record
from test_tests_policy_gate import isolated, project


def piped_project(tmp_path: Path) -> Path:
    cwd = tmp_path / "project"
    cwd.mkdir()
    os.mkfifo(cwd / "out.pipe")
    return project(cwd)


def recorded(cwd: Path, call: tuple[str, dict]) -> dict:
    tool_name, tool_input = call
    payload = {"session_id": "t19", "cwd": str(cwd), "tool_name": tool_name, "turn_id": "turn",
               "tool_use_id": "use", "tool_input": tool_input,
               "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}
    return record.run(payload, isolated(cwd))


@pytest.mark.parametrize("call", [
    pytest.param(("Write", {"file_path": "/dev/null", "content": "hello"}), id="write-to-dev-null"),
    pytest.param(("Bash", {"command": "printf hello > gone.md && rm gone.md"}), id="deleted-in-the-same-command"),
])
def test_a_target_that_holds_nothing_after_the_run_owes_no_unscannable_row(tmp_path: Path, call: tuple) -> None:
    assert "unscannable_file" not in recorded(piped_project(tmp_path), call).get("reason", "")


@pytest.mark.parametrize("call", [
    pytest.param(("Bash", {"command": "printf hello > out.pipe"}), id="fifo"),
    pytest.param(("Bash", {"command": "printf hello > '$M.md'"}), id="dollar-in-name"),
])
def test_a_target_that_may_still_hide_text_keeps_its_unscannable_row(tmp_path: Path, call: tuple) -> None:
    assert "unscannable_file" in recorded(piped_project(tmp_path), call).get("reason", "")
