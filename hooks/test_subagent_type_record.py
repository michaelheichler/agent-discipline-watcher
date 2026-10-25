"""Because a host may send a later hook payload with the agent id but no type, the test gate must recall the type SubagentStart saw."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

import subagent_start
from lib import protected, tests_policy
from test_tests_policy_gate import TEST_BODY, blocked_by, isolated, project, write


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def started_project(tmp_path: Path, agent_type: str) -> Path:
    cwd = project(tmp_path, tests="deny")
    payload = {"session_id": "t19", "hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": agent_type}
    subagent_start.run(payload, isolated(cwd))
    return cwd


def test_a_started_test_writer_writes_a_test_by_its_agent_id_alone(tmp_path: Path) -> None:
    cwd = started_project(tmp_path, tests_policy.TEST_WRITER)
    assert not blocked_by(write(cwd / "test_total.py", TEST_BODY, agent_id="a1"), tests_policy.RULE)


@pytest.mark.parametrize(("agent_type", "agent_id"), [
    pytest.param(tests_policy.TEST_WRITER, "a2", id="unknown-id"),
    pytest.param("general-purpose", "a1", id="other-type"),
])
def test_an_id_not_tied_to_the_test_writer_stays_blocked(tmp_path: Path, agent_type: str, agent_id: str) -> None:
    cwd = started_project(tmp_path, agent_type)
    assert blocked_by(write(cwd / "test_total.py", TEST_BODY, agent_id=agent_id), tests_policy.RULE)


@pytest.mark.parametrize(("typed", "untyped_row"), [
    pytest.param({}, True, id="id-without-type"),
    pytest.param({"agent_type": "general-purpose"}, False, id="id-with-type"),
])
def test_a_denied_row_says_when_the_payload_named_no_agent_type(tmp_path: Path, typed: dict, untyped_row: bool) -> None:
    cwd = started_project(tmp_path, tests_policy.TEST_WRITER)
    payload = {"session_id": "t19", "cwd": str(cwd), "agent_id": "a2", **typed}
    gate = tests_policy.Gate(payload, {"tests": "deny", **isolated(cwd)}, time.time())

    rows = tests_policy.findings(gate, [tests_policy.PendingChange(str(cwd / "test_total.py"), None, TEST_BODY)])

    assert rows[0]["detail"].startswith(tests_policy.UNTYPED_DETAIL) is untyped_row
