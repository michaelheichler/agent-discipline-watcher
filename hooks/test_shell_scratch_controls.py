"""Retain opaque-source refusals because scratch output can later enter the project."""
from __future__ import annotations

import json

import pytest

import pre_bash


@pytest.mark.parametrize("command,required", [
    pytest.param("dd if=/dev/zero of=/tmp/x count=1", {"opaque_source_write"}, id="dd"),
    pytest.param("cat <(echo hi) > /tmp/y", {"opaque_source_write"}, id="process-stream"),
    pytest.param("dd if=/dev/zero of=/tmp/x count=1 && cp /tmp/x app.py",
                 {"opaque_source_write"}, id="dd-then-copy"),
    pytest.param("cat <(printf 'def test_sample(): pass') > /tmp/y && cp /tmp/y test_sample.py",
                 {"opaque_source_write", "test_write_gate"}, id="test-stream-then-copy"),
])
def test_scratch_streams_cannot_launder_unscannable_content_into_a_project(
        tmp_path, monkeypatch, command, required) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".agent-discipline.json").write_text('{"tests":"deny"}', encoding="utf-8")
    payload = {"cwd": str(tmp_path), "session_id": "scratch-control", "tool_name": "Bash",
               "tool_input": {"command": command}}
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}

    response = pre_bash.run(payload, config)

    assert response.get("decision") == "block"
    rows = (tmp_path / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert required <= {json.loads(row).get("rule") for row in rows}


def test_a_read_only_process_stream_stays_allowed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    payload = {"cwd": str(tmp_path), "session_id": "read-only-stream", "tool_name": "Bash",
               "tool_input": {"command": "cat <(echo hi)"}}
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}

    response = pre_bash.run(payload, config)

    assert response.get("decision") != "block"
