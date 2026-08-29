from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import threading
import pytest

from lib import claude_journal, claude_luna, claude_native
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from lib.luna_provider import LunaJudge
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

    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    response = claude_luna.run(
        _post_payload(source), provider=provider, state_root=tmp_path / "state",
        settings_path=settings, preset_path=preset,
    )

    assert provider.requests
    request = provider.requests[0]
    assert request.review_kind is ReviewKind.COMMENT
    assert request.candidates == ("Counts the retries because the report header needs a total.",)
    assert "raw host content" not in json.dumps(request.__dict__ if hasattr(request, "__dict__") else request.candidates)
    assert "raw response content" not in json.dumps(request.candidates)
    assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "the opening names behavior" in response["hookSpecificOutput"]["additionalContext"]


def test_post_handler_caps_huge_candidates_across_all_edited_files_before_judging(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    huge = "Counts the retries because " + ("the report header needs a total " * 40)
    first.write_text(f"# {huge}\nvalue = 1\n", encoding="utf-8")
    second.write_text("# Tracks the cache because retries must remain bounded.\nvalue = 2\n", encoding="utf-8")
    patch = f"*** Update File: {first.name}\n@@\n*** Update File: {second.name}\n@@"
    payload = {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
        "tool_name": "apply_patch", "tool_use_id": "tool-1", "tool_input": {"input": patch},
    }
    provider = Provider(lambda request: _result(request, {"items": []}))

    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    claude_luna.run(
        payload, provider=provider, state_root=tmp_path / "state",
        settings_path=settings, preset_path=preset,
    )

    assert provider.requests
    request = provider.requests[0]
    assert len(request.candidates) <= claude_journal.MAX_ROWS
    assert request.candidates == tuple(item[:claude_journal.MAX_CANDIDATE_CHARS] for item in request.candidates)
    assert any("Counts the retries" in item for item in request.candidates)
    assert any("Tracks the cache" in item for item in request.candidates)


def test_post_handler_bounds_paths_file_bytes_and_total_scan_before_extracting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_luna, "MAX_LIVE_PATHS", 2)
    monkeypatch.setattr(claude_luna, "MAX_LIVE_FILE_BYTES", 100)
    monkeypatch.setattr(claude_luna, "MAX_LIVE_SCAN_BYTES", 150)
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    last = tmp_path / "last.py"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("value = 2\n", encoding="utf-8")
    last.write_text("# Counts the retries because the report header needs a total.\nvalue = 3\n", encoding="utf-8")
    oversized = tmp_path / "oversized.py"
    oversized.write_text("# " + ("x" * 200) + "\n# Counts the retries because the report header needs a total.\n", encoding="utf-8")
    patch = "\n".join(f"*** Update File: {path.name}\n@@" for path in (first, second, last))
    payload = {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
        "tool_name": "apply_patch", "tool_use_id": "tool-1", "tool_input": {"input": patch},
    }
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    provider = Provider(lambda request: _result(request, {"items": []}))

    claude_luna.run(payload, provider=provider, settings_path=settings, preset_path=preset)

    assert provider.requests == []
    oversized_payload = {
        **payload,
        "tool_input": {"input": "*** Update File: oversized.py\n@@"},
    }
    claude_luna.run(oversized_payload, provider=provider, settings_path=settings, preset_path=preset)
    assert provider.requests == []

    monkeypatch.setattr(claude_luna, "MAX_LIVE_PATHS", 10)
    monkeypatch.setattr(claude_luna, "MAX_LIVE_SCAN_BYTES", 25)
    total_payload = {
        **payload,
        "tool_input": {"input": "\n".join(f"*** Update File: {path.name}\n@@" for path in (first, second, last))},
    }
    claude_luna.run(total_payload, provider=provider, settings_path=settings, preset_path=preset)
    assert provider.requests == []


@pytest.mark.parametrize("tool_name, field", [("apply_patch", "input"), ("Bash", "command")])
def test_live_path_extraction_caps_raw_patch_or_bash_before_payload_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_name: str, field: str,
) -> None:
    source = tmp_path / "candidate.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    calls = 0

    def forbidden_parser(_payload: object) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        raise AssertionError("raw oversized input must not reach edited_paths")

    monkeypatch.setattr(claude_luna.payloads, "edited_paths", forbidden_parser)
    oversized = "*** Update File: candidate.py\n" + ("x" * (claude_luna.MAX_LIVE_SCAN_BYTES * 2))
    payload = {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
        "tool_name": tool_name, "tool_use_id": "tool-1", "tool_input": {field: oversized},
    }

    assert claude_luna._read_candidates(payload) == ()
    assert calls == 0


def test_live_path_extraction_fails_open_for_malformed_unicode_edit_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_parser(_payload: object) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        raise AssertionError("malformed raw input must not reach edited_paths")

    monkeypatch.setattr(claude_luna.payloads, "edited_paths", forbidden_parser)
    payload = {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
        "tool_name": "apply_patch", "tool_use_id": "tool-1",
        "tool_input": {"input": "*** Update File: candidate.py\n\ud800"},
    }

    assert claude_luna._read_candidates(payload) == ()
    assert calls == 0


def test_live_read_rejects_symlinked_parent_components(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    source = real_root / "candidate.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    alias_root = tmp_path / "alias"
    alias_root.symlink_to(real_root, target_is_directory=True)
    payload = _post_payload(alias_root / "candidate.py")

    assert claude_luna._read_candidates(payload) == ()


def test_live_read_rejects_same_size_inode_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "candidate.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    original_fstat = claude_luna.os.fstat
    regular_calls = 0

    def swapped_fstat(descriptor: int):
        nonlocal regular_calls
        metadata = original_fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            regular_calls += 1
        if regular_calls == 2:
            values = list(metadata)
            values[1] += 1
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(claude_luna.os, "fstat", swapped_fstat)

    assert claude_luna._read_candidates(_post_payload(source)) == ()


def test_queued_luna_call_cannot_begin_provider_spend_after_failure_commits_mixed(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    source = tmp_path / "candidate.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    class Provider:
        def judge(self, request: JudgeRequest) -> JudgeResult:
            nonlocal calls
            with calls_lock:
                calls += 1
                number = calls
            if number == 1:
                first_started.set()
                assert release_first.wait(2)
                raise LunaProviderFailure("subscription unavailable", category="authentication")
            second_started.set()
            return _result(request, {"items": []})

    provider = Provider()
    responses: list[dict] = []

    def invoke() -> None:
        responses.append(claude_luna.run(
            _post_payload(source), provider=provider,
            settings_path=settings, preset_path=preset,
        ))

    first = threading.Thread(target=invoke)
    first.start()
    assert first_started.wait(2)
    second = threading.Thread(target=invoke)
    second.start()
    release_first.set()
    first.join(3)
    second.join(3)

    assert not first.is_alive() and not second.is_alive()
    assert calls == 1
    assert not second_started.is_set()
    assert claude_native.read_preset(preset) == "mixed"


def test_deleted_journal_target_removes_stale_rows_and_stop_has_no_stale_document(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    state_root = tmp_path / "state"
    document.write_text("A paragraph that was journalled.\n", encoding="utf-8")
    assert claude_journal.record_edit("session", "turn", "tool", document, state_root=state_root)
    document.unlink()

    assert claude_journal.record_edit("session", "turn-2", "tool-2", document, state_root=state_root) == []
    assert claude_journal.read("session", state_root=state_root) == []
    assert claude_luna.stop_request(
        {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False}, state_root,
    ) is None


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


def test_live_luna_command_valid_event_success_has_production_response_shape(tmp_path: Path) -> None:
    source = tmp_path / "clean.py"
    source.write_text("value = 1\n", encoding="utf-8")
    command = claude_native.generated_hooks("luna")["PostToolUse"][0]["hooks"][0]["command"]
    result = subprocess.run(
        command, shell=True,
        input=json.dumps({
            "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
            "tool_name": "Write", "tool_use_id": "tool-1", "tool_input": {"file_path": str(source)},
        }),
        env={**os.environ, "HOME": str(tmp_path / "home")}, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


def test_live_luna_command_uses_a_valid_cache_hit_for_success_without_spending_again(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "candidate.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    payload = {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
        "tool_name": "Write", "tool_use_id": "tool-1", "tool_input": {"file_path": str(source)},
    }
    built = claude_luna.post_request(payload)
    assert built is not None
    request = built[0]
    result = _result(request, {
        "items": [{"index": 0, "verdict": "states_why", "reason": "names a reason"}],
    })
    judge = LunaJudge(
        runtime_root=home / ".adw" / "runtime", cache_root=home / ".adw" / "cache" / "judges",
        auth_source=home / ".codex" / "auth.json",
    )
    cache_file = judge._cache_path(judge._cache_key(request))
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text(json.dumps({**result.__dict__, "cached": False}), encoding="utf-8")
    claude_native.set_preset("luna", settings_path=tmp_path / "settings.json", preset_path=tmp_path / "preset")
    command = claude_native.generated_hooks("luna")["PostToolUse"][0]["hooks"][0]["command"]

    process = subprocess.run(
        command, shell=True, input=json.dumps(payload),
        env={
            **os.environ, "HOME": str(home), "ADW_CLAUDE_SETTINGS": str(tmp_path / "settings.json"),
            "ADW_CLAUDE_PRESET_FILE": str(tmp_path / "preset"),
        }, capture_output=True, text=True, check=False,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {}
    assert claude_native.read_preset(tmp_path / "preset") == "luna"


def test_live_luna_command_valid_event_provider_failure_falls_back_once(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    source = tmp_path / "candidate.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    command = claude_native.generated_hooks("luna")["PostToolUse"][0]["hooks"][0]["command"]
    result = subprocess.run(
        command, shell=True,
        input=json.dumps({
            "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
            "tool_name": "Write", "tool_use_id": "tool-1", "tool_input": {"file_path": str(source)},
        }),
        env={
            **os.environ, "HOME": str(tmp_path / "home"), "ADW_CLAUDE_SETTINGS": str(settings),
            "ADW_CLAUDE_PRESET_FILE": str(preset),
        }, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "Luna" in response["hookSpecificOutput"]["additionalContext"]
    assert claude_native.read_preset(preset) == "mixed"
    configured = json.loads(settings.read_text(encoding="utf-8"))
    assert configured["hooks"]["PostToolUse"][0]["hooks"][0]["model"] == "haiku"
    assert configured["hooks"]["Stop"][0]["hooks"][0]["model"] == "sonnet"


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

    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    response = claude_luna.run(
        {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False},
        provider=provider, state_root=state_root, settings_path=settings, preset_path=preset,
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
    assert claude_native.read_preset(preset) == "mixed"
    configured = json.loads(settings.read_text(encoding="utf-8"))
    assert configured["hooks"]["PostToolUse"][0]["hooks"][0]["model"] == "haiku"


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
    assert claude_native.read_preset(preset) == "mixed"


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
    assert second == {}


def test_queued_luna_handler_skips_after_effective_preset_falls_back(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("mixed", settings_path=settings, preset_path=preset)
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    provider = Provider(error=AssertionError("stale Luna command must not judge"))

    response = claude_luna.run(
        _post_payload(source), provider=provider, settings_path=settings, preset_path=preset,
    )

    assert response == {}
    assert provider.requests == []


def test_live_luna_recovers_a_corrupt_transaction_and_runs_when_luna_is_current(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    preset.with_name(preset.name + ".txn").write_text("corrupt", encoding="utf-8")
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    provider = Provider(lambda request: _result(request, {
        "items": [{"index": 0, "verdict": "states_why", "reason": "names a reason"}],
    }))

    response = claude_luna.run(
        _post_payload(source), provider=provider, settings_path=settings, preset_path=preset,
    )

    assert response == {}
    assert provider.requests
    assert not preset.with_name(preset.name + ".txn").exists()
