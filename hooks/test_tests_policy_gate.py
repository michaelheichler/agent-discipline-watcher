"""Payload in, decision out, because the gate is a contract."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import pre_bash
import pre_write
from lib import protected, tests_policy

TEST_BODY = "def test_total():\n    assert total([1, 2]) == 3\n"
PLAIN_BODY = "def total(values):\n    return sum(values)\n"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def project(tmp_path: Path, **policy: object) -> Path:
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(policy), encoding="utf-8")
    return tmp_path


def isolated(tmp_path: Path) -> dict:
    return {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}


def write(target: Path, content: str, **extra: object) -> dict:
    payload = {"session_id": "t19", "cwd": str(target.parent), "tool_name": "Write",
               "tool_input": {"file_path": str(target), "content": content}, **extra}
    return pre_write.run(payload, isolated(target.parent))


def shell(cwd: Path, command: str, **extra: object) -> dict:
    payload = {"session_id": "t19", "cwd": str(cwd), "tool_name": "Bash",
               "tool_input": {"command": command}, **extra}
    return pre_bash.run(payload, isolated(cwd))


def blocked_by(response: dict, rule: str) -> bool:
    return response.get("decision") == "block" and rule in response.get("reason", "")


def test_deny_blocks_a_test_write_and_names_the_test_writer(tmp_path: Path) -> None:
    response = write(project(tmp_path, tests="deny") / "test_total.py", TEST_BODY)
    assert blocked_by(response, tests_policy.RULE)
    assert tests_policy.TEST_WRITER in response["reason"]


def test_deny_blocks_a_test_added_to_an_ordinary_module(tmp_path: Path) -> None:
    response = write(project(tmp_path, tests="deny") / "total.py", PLAIN_BODY + TEST_BODY)
    assert blocked_by(response, tests_policy.RULE)


def test_deny_blocks_an_edit_that_removes_a_test(tmp_path: Path) -> None:
    cwd = project(tmp_path, tests="deny")
    (cwd / "total.py").write_text(PLAIN_BODY + TEST_BODY, encoding="utf-8")
    payload = {"session_id": "t19", "cwd": str(cwd), "tool_name": "Edit", "tool_input": {
        "file_path": str(cwd / "total.py"), "old_string": TEST_BODY, "new_string": ""}}
    assert blocked_by(pre_write.run(payload, isolated(cwd)), tests_policy.RULE)


@pytest.mark.parametrize(("path", "text"), [
    ("tests/helpers.py", "VALUE = 1\n"),
    ("pkg/total_test.py", ""),
    ("web/cart.spec.ts", ""),
    ("web/cart.test.tsx", ""),
    ("src/lib.rs", "#[cfg(test)]\nmod checks {}\n"),
    ("src/lib.rs", "#[test]\nfn adds() { assert_eq!(2, 1 + 1); }\n"),
])
def test_common_test_shapes_count_as_tests(path: str, text: str) -> None:
    assert tests_policy.touches_tests(tests_policy.PendingChange(path, None, text))


def test_a_rust_module_without_tests_is_production_code() -> None:
    change = tests_policy.PendingChange("src/lib.rs", None, "pub fn add() -> i32 { 2 }\n")
    assert not tests_policy.touches_tests(change)


def test_default_allow_lets_a_test_write_pass(tmp_path: Path) -> None:
    assert not blocked_by(write(tmp_path / "test_total.py", TEST_BODY), tests_policy.RULE)


def test_deny_leaves_production_code_alone(tmp_path: Path) -> None:
    assert not blocked_by(write(project(tmp_path, tests="deny") / "total.py", PLAIN_BODY), tests_policy.RULE)


def test_the_test_writer_agent_passes(tmp_path: Path) -> None:
    cwd = project(tmp_path, tests="deny")
    response = write(cwd / "test_total.py", TEST_BODY, agent_id="a1", agent_type=tests_policy.TEST_WRITER)
    assert not blocked_by(response, tests_policy.RULE)


def test_another_agent_type_stays_blocked(tmp_path: Path) -> None:
    response = write(project(tmp_path, tests="deny") / "test_total.py", TEST_BODY, agent_type="general-purpose")
    assert blocked_by(response, tests_policy.RULE)


def test_an_open_window_lets_any_agent_write_tests(tmp_path: Path) -> None:
    cwd = project(tmp_path, tests="deny", tests_allow_until=int(time.time()) + 600)
    assert not blocked_by(write(cwd / "test_total.py", TEST_BODY), tests_policy.RULE)


def test_an_expired_window_blocks_again(tmp_path: Path) -> None:
    cwd = project(tmp_path, tests="deny", tests_allow_until=int(time.time()) - 1)
    assert blocked_by(write(cwd / "test_total.py", TEST_BODY), tests_policy.RULE)


def test_the_window_closes_at_its_expiry() -> None:
    settings = {"tests": "deny", tests_policy.WINDOW_KEY: 1000}
    assert tests_policy.gate_open(tests_policy.Gate({}, settings, 999.0))
    assert not tests_policy.gate_open(tests_policy.Gate({}, settings, 1000.0))


def test_a_shell_redirect_into_a_test_file_is_blocked(tmp_path: Path) -> None:
    response = shell(project(tmp_path, tests="deny"), "echo 'x = 1' > tests/test_total.py")
    assert blocked_by(response, tests_policy.RULE)


def test_a_shell_delete_of_a_test_file_is_blocked(tmp_path: Path) -> None:
    cwd = project(tmp_path, tests="deny")
    (cwd / "test_total.py").write_text(TEST_BODY, encoding="utf-8")
    assert blocked_by(shell(cwd, "rm test_total.py"), tests_policy.RULE)


def test_the_test_writer_agent_passes_the_shell_gate(tmp_path: Path) -> None:
    cwd = project(tmp_path, tests="deny")
    response = shell(cwd, "echo 'x = 1' > tests/test_total.py", agent_type=tests_policy.TEST_WRITER)
    assert not blocked_by(response, tests_policy.RULE)


def test_omp_advice_asks_for_a_timed_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMPCODE", "1")
    response = write(project(tmp_path, tests="deny") / "test_total.py", TEST_BODY)
    assert blocked_by(response, tests_policy.RULE)
    assert tests_policy.WINDOW_HINT in response["reason"]
