"""Run the real PreToolUse entry in a child process, because opening a named pipe to read it waits for a writer and can hang the session."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib import protected, tests_policy
from test_tests_policy_gate import project

HOOKS = Path(__file__).parent
DEADLINE_SECONDS = 5


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def fifo_project(tmp_path: Path, fifo: str) -> Path:
    cwd = tmp_path / "project"
    (cwd / fifo).parent.mkdir(parents=True)
    (cwd / "action.sh").write_text("echo hi\n", encoding="utf-8")
    os.mkfifo(cwd / fifo)
    return project(cwd, tests="deny")


def pre_tool_answer(tmp_path: Path, payload: dict) -> dict | None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    try:
        done = subprocess.run(
            [sys.executable, "pre_tool.py"], input=json.dumps({"session_id": "t19", **payload}), text=True,
            capture_output=True, cwd=HOOKS, env={**os.environ, "HOME": str(home)}, timeout=DEADLINE_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    return json.loads(done.stdout)


def denied_by(answer: dict | None, rule: str = "") -> bool:
    output = (answer or {}).get("hookSpecificOutput", {})
    return output.get("permissionDecision") == "deny" and rule in output.get("permissionDecisionReason", "")


def test_a_command_that_feeds_a_named_pipe_gets_an_answer(tmp_path: Path) -> None:
    cwd = fifo_project(tmp_path, "input.pipe")
    command = "cat action.sh > input.pipe & bash input.pipe"
    payload = {"cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": command}}
    assert pre_tool_answer(tmp_path, payload) is not None


def test_a_shell_write_to_a_test_path_that_is_a_named_pipe_is_denied(tmp_path: Path) -> None:
    cwd = fifo_project(tmp_path, "tests/test_x.py")
    payload = {"cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": "printf hello > tests/test_x.py"}}
    assert denied_by(pre_tool_answer(tmp_path, payload), tests_policy.RULE)


def test_a_write_tool_call_aimed_at_a_named_pipe_is_denied(tmp_path: Path) -> None:
    cwd = fifo_project(tmp_path, "input.pipe")
    payload = {"cwd": str(cwd), "tool_name": "Write",
               "tool_input": {"file_path": str(cwd / "input.pipe"), "content": "echo hi\n"}}
    assert denied_by(pre_tool_answer(tmp_path, payload))
