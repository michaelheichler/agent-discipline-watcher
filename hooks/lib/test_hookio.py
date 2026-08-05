from __future__ import annotations

import io

from lib import hookio


def test_empty_stdin_returns_empty_payload(monkeypatch) -> None:
    monkeypatch.setattr(hookio.sys, "stdin", io.StringIO(""))
    assert hookio.read_payload() == {}


def test_valid_json_returns_parsed_payload(monkeypatch) -> None:
    monkeypatch.setattr(hookio.sys, "stdin", io.StringIO('{"tool_name": "Write"}'))
    assert hookio.read_payload() == {"tool_name": "Write"}


def test_malformed_json_returns_parse_failure_signal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(hookio.sys, "stdin", io.StringIO("not json {"))
    assert hookio.read_payload() is hookio.PARSE_FAILURE
    assert capsys.readouterr().err.startswith("agent-discipline-watcher: unreadable hook payload")
