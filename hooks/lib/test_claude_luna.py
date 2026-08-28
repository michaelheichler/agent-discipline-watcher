from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from lib import claude_journal, claude_luna, claude_native
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from lib.luna_storage import LunaProviderFailure


def _result(request: JudgeRequest, payload: dict) -> JudgeResult:
    return JudgeResult(
        payload=payload, provider="openai-codex", model="gpt-5.6-luna", effort="high",
        rubric_version=request.rubric_version, usage={"input_tokens": 1},
    )


class Provider:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result(request) if callable(self.result) else self.result


def _post_payload(path: Path) -> dict:
    return {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(path.parent),
        "tool_name": "Write", "tool_use_id": "tool-1",
        "tool_input": {"file_path": str(path), "content": "raw host content"},
        "tool_response": {"filePath": str(path), "content": "raw response content"},
    }


def test_post_handler_extracts_the_just_written_candidate_without_waiting_for_journal(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    provider = Provider(lambda request: _result(request, {
        "items": [{"index": 0, "verdict": "describes_code", "reason": "the opening names behavior"}],
    }))

    response = claude_luna.run(_post_payload(source), provider=provider, state_root=tmp_path / "state")

    assert provider.requests
    request = provider.requests[0]
    assert request.review_kind is ReviewKind.COMMENT
    assert request.candidates == ("Counts the retries because the report header needs a total.",)
    assert "raw host content" not in json.dumps(request.__dict__ if hasattr(request, "__dict__") else request.candidates)
    assert "raw response content" not in json.dumps(request.candidates)
    assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "the opening names behavior" in response["hookSpecificOutput"]["additionalContext"]


def test_post_handler_fails_open_for_irrelevant_or_malformed_input(tmp_path: Path) -> None:
    provider = Provider(error=AssertionError("must not judge"))

    assert claude_luna.run({}, provider=provider) == {}
    assert claude_luna.run({"hook_event_name": "PostToolUse", "tool_name": "Read"}, provider=provider) == {}
    assert claude_luna.run(
        {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": "relative.py"}},
        provider=provider,
    ) == {}
    assert claude_luna.run(
        {"hook_event_name": "PostToolUse", "cwd": "\x00", "tool_name": "Write", "tool_input": {"file_path": "x.py"}},
        provider=provider,
    ) == {}
    assert claude_luna.run(
        {"hook_event_name": "Stop", "session_id": "../outside", "stop_hook_active": False},
        provider=provider,
    ) == {}
    assert provider.requests == []


def test_live_luna_command_routes_raw_hook_input_through_the_resolver(tmp_path: Path) -> None:
    command = claude_native.generated_hooks("luna")["PostToolUse"][0]["hooks"][0]["command"]
    result = subprocess.run(
        command, shell=True, input=json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Read"}),
        env={**os.environ, "HOME": str(tmp_path)}, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "{}"


def test_exact_stop_reader_script_returns_only_current_session_documents(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    document.write_text("Only the current session document.\n", encoding="utf-8")
    state_root = tmp_path / ".adw" / "state"
    claude_journal.record_edit("session", "turn", "tool", document, state_root=state_root)
    reader = Path(__file__).parents[1] / "read_claude_journal.sh"
    result = subprocess.run(
        [str(reader), "session"], env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Only the current session document." in result.stdout


def test_stop_handler_reads_only_bounded_current_session_journal(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    document.write_text("A paragraph with enough text to inspect.\n", encoding="utf-8")
    unrelated = tmp_path / "unrelated.md"
    unrelated.write_text("Never read this unrelated document.\n", encoding="utf-8")
    state_root = tmp_path / "state"
    claude_journal.record_edit("session", "turn", "tool", document, state_root=state_root)
    claude_journal.record_edit("other-session", "turn", "tool", unrelated, state_root=state_root)
    provider = Provider(lambda request: _result(request, {
        "notes": [{"quote": "A paragraph with enough text to inspect.", "problem": "weak bridge", "fix": "Name the transition."}],
    }))

    response = claude_luna.run(
        {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False},
        provider=provider, state_root=state_root,
    )

    request = provider.requests[0]
    assert request.review_kind is ReviewKind.DOCUMENT
    assert "doc.md" in request.source_context
    assert "Never read this unrelated" not in request.source_context
    assert response["decision"] == "block"
    assert "weak bridge" in response["reason"]


def test_stop_handler_skips_provider_when_stop_is_already_active_or_journal_is_empty() -> None:
    provider = Provider(error=AssertionError("must not judge"))

    assert claude_luna.run({"hook_event_name": "Stop", "session_id": "s", "stop_hook_active": True}, provider=provider) == {}
    assert claude_luna.run({"hook_event_name": "Stop", "session_id": "missing", "stop_hook_active": False}, provider=provider) == {}
    assert provider.requests == []


def test_luna_success_has_no_native_double_spend_and_failure_switches_the_matching_role(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")

    success = Provider(lambda request: _result(request, {
        "items": [{"index": 0, "verdict": "states_why", "reason": "names a reason"}],
    }))
    assert claude_luna.run(_post_payload(source), provider=success, settings_path=settings, preset_path=preset) == {}
    assert claude_native.read_preset(preset) == "luna"

    failure = Provider(error=LunaProviderFailure("login required", category="authentication"))
    response = claude_luna.run(
        _post_payload(source), provider=failure, settings_path=settings, preset_path=preset,
    )
    assert "login required" in response["hookSpecificOutput"]["additionalContext"]
    assert claude_native.read_preset(preset) == "haiku"
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["hooks"][0]["model"] == "haiku"


def test_luna_stop_failure_switches_to_sonnet_once(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    document = tmp_path / "doc.md"
    document.write_text("A paragraph with enough text to inspect.\n", encoding="utf-8")
    state_root = tmp_path / "state"
    claude_journal.record_edit("session", "turn", "tool", document, state_root=state_root)
    failure = Provider(error=LunaProviderFailure("subscription unavailable", category="authentication"))

    response = claude_luna.run(
        {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False},
        provider=failure, state_root=state_root, settings_path=settings, preset_path=preset,
    )

    assert response["decision"] == "block"
    assert "subscription unavailable" in response["reason"]
    assert claude_native.read_preset(preset) == "sonnet"


def test_luna_failure_reports_no_second_transition_after_role_fallback_is_active(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    failure = Provider(error=LunaProviderFailure("login required", category="authentication"))

    first = claude_luna.run(
        _post_payload(source), provider=failure, settings_path=settings, preset_path=preset,
    )
    second = claude_luna.run(
        _post_payload(source), provider=failure, settings_path=settings, preset_path=preset,
    )

    assert "Switched subsequent events" in first["hookSpecificOutput"]["additionalContext"]
    assert "Switched subsequent events" not in second["hookSpecificOutput"]["additionalContext"]
    assert "remains configured" in second["hookSpecificOutput"]["additionalContext"]
