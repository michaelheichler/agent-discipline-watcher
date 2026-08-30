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

def test_write_payload_bounds_non_message_fields(capsys) -> None:
    hookio.write_payload({
        "decision": "x" * 10_000,
        "reason": "reason",
        "hookSpecificOutput": {
            "hookEventName": "e" * 10_000,
            "permissionDecision": "p" * 10_000,
        },
    })
    output = capsys.readouterr().out
    assert len(output.encode("utf-8")) <= hookio.MAX_RESPONSE_BYTES + 1
    payload = json.loads(output)
    assert len(payload["decision"]) <= 64
    assert len(payload["hookSpecificOutput"]["hookEventName"]) <= 128
    assert len(payload["hookSpecificOutput"]["permissionDecision"]) <= 32


def test_fitting_payload_preserves_complete_context() -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": hookio.CONTRACT,
        },
    }
    assert hookio._bounded_payload(payload) == payload
    assert hookio._bounded_payload(payload)["hookSpecificOutput"]["additionalContext"] == hookio.CONTRACT


def test_write_payload_preserves_complete_fitting_context(capsys) -> None:
    hookio.write_payload({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": hookio.CONTRACT,
        },
    })
    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["additionalContext"] == hookio.CONTRACT

def test_fitting_message_fields_strip_controls(capsys) -> None:
    hookio.write_payload({
        "systemMessage": "safe\r\u0085\u202e",
        "hookSpecificOutput": {"additionalContext": "context\u2066"},
    })
    output = json.loads(capsys.readouterr().out)
    assert "\r" not in output["systemMessage"]
    assert "\u0085" not in output["systemMessage"]
    assert "\u202e" not in output["systemMessage"]
    assert "\u2066" not in output["hookSpecificOutput"]["additionalContext"]

def test_oversized_stdin_is_rejected_before_json_parse(monkeypatch) -> None:
    monkeypatch.setattr(hookio.sys, "stdin", io.StringIO("x" * (hookio.MAX_INPUT_CHARS + 1)))
    assert hookio.read_payload() is hookio.PARSE_FAILURE

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
