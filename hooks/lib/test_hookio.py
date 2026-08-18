from __future__ import annotations

import io
import json

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


def test_deeply_nested_json_is_a_parse_failure_not_a_crash(monkeypatch) -> None:
    nested = "[" * 20000 + "]" * 20000
    monkeypatch.setattr(hookio.sys, "stdin", io.StringIO(nested))
    assert hookio.read_payload() is hookio.PARSE_FAILURE


def test_write_payload_hard_bounds_repeated_hook_text(capsys) -> None:
    reason = "x" * 100_000

    hookio.write_payload({
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    })

    output = capsys.readouterr().out
    assert len(output.encode("utf-8")) <= hookio.MAX_RESPONSE_BYTES + 1
    assert json.loads(output)["decision"] == "block"


def test_fail_closed_returns_the_function_result_when_it_does_not_raise() -> None:
    assert hookio.fail_closed("write", lambda: {"ok": True}) == {"ok": True}


def test_fail_closed_denies_naming_the_subject_and_cause_on_exception() -> None:
    def _raise() -> dict:
        raise ValueError("bad state")

    response = hookio.fail_closed("write", _raise)

    assert response["decision"] == "block"
    assert "this write" in response["reason"]
    assert "Cause: bad state" in response["reason"]


def test_claude_pretool_response_removes_deprecated_top_level_block() -> None:
    response = hookio.claude_pretool_response(hookio.deny("fix and retry"))
    assert "decision" not in response
    assert "reason" not in response
    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "fix and retry",
        }
    }
