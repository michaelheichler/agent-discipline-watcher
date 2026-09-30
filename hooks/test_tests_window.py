"""Guarded, because an agent that edits these opens the gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pre_bash
import pre_write
from lib import adw_config, protected, tests_policy

NOW = 1_000_000.0
DEFINITIONS = (
    ".claude/agents/adw-test-writer.md",
    ".codex/agents/adw-test-writer.toml",
    ".omp/agents/adw-test-writer.md",
    ".omp/agent/agents/adw-test-writer.md",
    "agents/adw-test-writer.md",
)


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)


def policy(cwd: Path) -> dict:
    return json.loads((cwd / ".agent-discipline.json").read_text(encoding="utf-8"))


def isolated(tmp_path: Path) -> dict:
    return {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}


def test_allow_for_stores_an_expiry_that_status_counts_down(tmp_path: Path, capsys) -> None:
    assert adw_config.run(["tests", "allow", "--for", "30m"], tmp_path, NOW) == 0
    assert policy(tmp_path)[tests_policy.WINDOW_KEY] == NOW + 1800
    capsys.readouterr()
    adw_config.run(["status"], tmp_path, NOW + 1020)
    assert "13m" in capsys.readouterr().out
    assert tests_policy.window_seconds_left(policy(tmp_path), NOW + 1800) == 0


@pytest.mark.parametrize("duration", ["9h", "481m", "30s", "0m", "later"])
def test_a_window_past_the_cap_or_malformed_is_refused(tmp_path: Path, duration: str) -> None:
    with pytest.raises(adw_config.configure_policy.ConfigureError):
        adw_config.run(["tests", "allow", "--for", duration], tmp_path, NOW)
    assert not (tmp_path / ".agent-discipline.json").exists()


def test_deny_closes_an_open_window(tmp_path: Path) -> None:
    adw_config.run(["tests", "allow", "--for", "2h"], tmp_path, NOW)
    adw_config.run(["tests", "deny"], tmp_path, NOW)
    assert tests_policy.window_seconds_left(policy(tmp_path), NOW) == 0


def test_an_agent_edit_that_opens_the_window_is_sealed(tmp_path: Path) -> None:
    target = tmp_path / ".agent-discipline.json"
    target.write_text('{"tests": "deny"}', encoding="utf-8")
    payload = {"session_id": "t19", "cwd": str(tmp_path), "tool_name": "Edit", "tool_input": {
        "file_path": str(target), "old_string": '"deny"}', "new_string": '"deny", "tests_allow_until": 9999999999}'}}
    response = pre_write.run(payload, isolated(tmp_path))
    assert response.get("decision") == "block"
    assert "config_seal" in response["reason"]


def test_a_shell_write_that_opens_the_window_is_blocked(tmp_path: Path) -> None:
    (tmp_path / ".agent-discipline.json").write_text('{"tests": "deny"}', encoding="utf-8")
    command = "echo '{\"tests\": \"deny\", \"tests_allow_until\": 9999999999}' > .agent-discipline.json"
    payload = {"session_id": "t19", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": command}}
    assert pre_bash.run(payload, isolated(tmp_path)).get("decision") == "block"


def test_a_shell_route_to_open_the_window_is_blocked() -> None:
    response = pre_bash.run({"tool_input": {"command": "adw-config tests allow --for 30m"}}, {})
    assert response.get("decision") == "block"
    assert "config_seal" in response["reason"]


@pytest.mark.parametrize("relative", DEFINITIONS)
def test_an_agent_write_to_a_test_writer_definition_is_blocked(tmp_path: Path, relative: str) -> None:
    target = tmp_path / relative
    rules = [row["rule"] for row in protected.path_findings(str(target), {}, tmp_path, "name: x\n")]
    assert rules == ["test_writer_definition"]


def test_a_shell_delete_of_the_user_definition_is_blocked(tmp_path: Path) -> None:
    command = "rm ~/.claude/agents/adw-test-writer.md"
    rows = pre_bash.target_findings(command, {}, tmp_path)
    assert [row["rule"] for row in rows] == ["test_writer_definition"]


def test_other_agent_definitions_stay_editable(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "agents" / "reviewer.md"
    assert protected.path_findings(str(target), {}, tmp_path, "name: reviewer\n") == []
