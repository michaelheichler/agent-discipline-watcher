from __future__ import annotations
# pylint: disable=too-few-public-methods

import json
import tomllib
from pathlib import Path

import pytest

import session_end
import session_start
import stop
import subagent_start
from lib import claude_journal, codex_luna, reporting, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from lib.luna_storage import LunaProviderFailure


ROOT = Path(__file__).resolve().parents[1]


class Provider:
    def __init__(self, result: JudgeResult | None = None, error: Exception | None = None) -> None:
        self.calls: list[JudgeRequest] = []
        self.result = result
        self.error = error

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FlakyProvider(Provider):
    def __init__(self, first_error: Exception, result: JudgeResult) -> None:
        super().__init__(result=result)
        self.first_error = first_error

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.calls.append(request)
        if len(self.calls) == 1:
            raise self.first_error
        assert self.result is not None
        return self.result


def _result(request_kind: ReviewKind = ReviewKind.COMMENT) -> JudgeResult:
    payload = {"items": []} if request_kind is ReviewKind.COMMENT else {"notes": []}
    return JudgeResult(
        payload=payload,
        provider="openai-codex",
        model="gpt-5.6-luna",
        effort="high",
        rubric_version="adw-rubric-v1",
        usage={"total_tokens": 1},
    )


def test_codex_snippet_wires_only_documented_stop_and_session_end_command_fields() -> None:
    parsed = tomllib.loads(
        (ROOT / "hooks" / "codex-config.snippet.toml")
        .read_text(encoding="utf-8")
        .replace("__SKILL_DIR__", "/tmp/adw")
    )
    assert "Stop" in parsed["hooks"]
    assert "SessionEnd" in parsed["hooks"]
    for event in ("Stop", "SessionEnd"):
        for group in parsed["hooks"][event]:
            assert set(group) <= {"matcher", "hooks"}
            for hook in group["hooks"]:
                assert set(hook) <= {"type", "command", "timeout", "async", "statusMessage", "additionalContextLimit"}
                assert hook["type"] == "command"
                assert "run.sh" in hook["command"]
                assert event in hook["command"]


def test_session_and_subagent_start_use_one_short_model_channel_without_readable_skill() -> None:
    for event, output in (("SessionStart", session_start.run({})), ("SubagentStart", subagent_start.run({}))):
        assert "systemMessage" not in output
        specific = output["hookSpecificOutput"]
        assert specific["hookEventName"] == event
        assert set(specific) == {"hookEventName", "additionalContext"}
        context = specific["additionalContext"]
        assert "READABLE OUTPUT RULES ACTIVE" not in context
        assert "### 1. Lead with the next action" not in context
        assert len(context.encode("utf-8")) <= 4096


def test_codex_stop_judges_current_session_journal_once_and_session_end_releases_lease(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    ledger_root = tmp_path / "ledger"
    config = {"state_root": str(state_root), "ledger_root": str(ledger_root)}
    source = tmp_path / "note.md"
    source.write_text("A short document.\n", encoding="utf-8")
    session_state.write_state("s1", {"turn_id": "turn-1"}, state_root)
    claude_journal.record_edit("s1", "turn-1", "tool-1", source, state_root=state_root)
    provider = Provider(_result(ReviewKind.DOCUMENT))

    first = stop.run({"session_id": "s1", "stop_hook_active": False, "cwd": str(tmp_path)}, config, provider=provider)
    second = stop.run({"session_id": "s1", "stop_hook_active": True, "cwd": str(tmp_path)}, config, provider=provider)

    assert first == {}
    assert second == {}
    assert len(provider.calls) == 1
    assert provider.calls[0].review_kind is ReviewKind.DOCUMENT
    source.write_text("A second document.\n", encoding="utf-8")
    claude_journal.record_edit("s1", "turn-2", "tool-2", source, state_root=state_root)
    third = stop.run(
        {"session_id": "s1", "turn_id": "turn-2", "stop_hook_active": False, "cwd": str(tmp_path)},
        config,
        provider=provider,
    )
    assert third == {}
    assert len(provider.calls) == 2
    assert session_state.live_session_ids(state_root) == frozenset({"s1"})
    session_end.run({"session_id": "s1"}, config)
    assert session_state.live_session_ids(state_root) == frozenset()


def test_codex_stop_provider_failure_is_one_bounded_actionable_block(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    source = tmp_path / "note.md"
    source.write_text("A short document.\n", encoding="utf-8")
    session_state.write_state("s1", {"turn_id": "turn-1"}, state_root)
    claude_journal.record_edit("s1", "turn-1", "tool-1", source, state_root=state_root)
    provider = Provider(error=LunaProviderFailure("subscription unavailable", category="authentication"))

    response = stop.run({"session_id": "s1", "stop_hook_active": False, "cwd": str(tmp_path)}, config, provider=provider)

    assert set(response) == {"decision", "reason"}
    assert response["decision"] == "block"
    assert response["reason"]
    assert len(response["reason"].encode("utf-8")) <= 4096
    assert len(provider.calls) == 1


def test_codex_stop_journal_failure_blocks_and_active_retry_does_not_silently_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    session_state.write_state("s1", {"turn_id": "turn-1"}, state_root)
    monkeypatch.setattr(codex_luna.claude_journal, "read", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("journal unavailable")))

    first = stop.run({"session_id": "s1", "stop_hook_active": False, "cwd": str(tmp_path)}, config, provider=Provider(_result(ReviewKind.DOCUMENT)))
    retry = stop.run({"session_id": "s1", "stop_hook_active": True, "cwd": str(tmp_path)}, config, provider=Provider(_result(ReviewKind.DOCUMENT)))

    assert first["decision"] == "block"
    assert "Luna review unavailable" in first["reason"]
    assert retry["decision"] == "block"
    assert "Luna review unavailable" in retry["reason"]


def test_codex_stop_provider_failure_rolls_back_reservation_for_retry(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    source = tmp_path / "note.md"
    source.write_text("A short document.\n", encoding="utf-8")
    session_state.write_state("s1", {"turn_id": "turn-1"}, state_root)
    claude_journal.record_edit("s1", "turn-1", "tool-1", source, state_root=state_root)
    provider = FlakyProvider(LunaProviderFailure("subscription unavailable", category="authentication"), _result(ReviewKind.DOCUMENT))

    first = stop.run({"session_id": "s1", "stop_hook_active": False, "cwd": str(tmp_path)}, config, provider=provider)
    retry = stop.run({"session_id": "s1", "stop_hook_active": True, "cwd": str(tmp_path)}, config, provider=provider)

    assert first["decision"] == "block"
    assert retry == {}
    assert len(provider.calls) == 2
    assert session_state.read_state("s1", state_root)[codex_luna.STATE_KEY] == ["turn-1"]


def test_codex_stop_failure_retry_without_turn_id_reuses_same_turn_and_clears_identity(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    source = tmp_path / "note.md"
    source.write_text("A short document.\n", encoding="utf-8")
    session_state.write_state("s1", {"turn_count": 1, "turn_id": "turn-1"}, state_root)
    claude_journal.record_edit("s1", "turn-1", "tool-1", source, state_root=state_root)
    provider = FlakyProvider(LunaProviderFailure("subscription unavailable", category="authentication"), _result(ReviewKind.DOCUMENT))

    first = stop.run({"session_id": "s1", "stop_hook_active": False, "cwd": str(tmp_path)}, config, provider=provider)
    retry = stop.run({"session_id": "s1", "stop_hook_active": True, "cwd": str(tmp_path)}, config, provider=provider)

    assert first["decision"] == "block"
    assert retry == {}
    assert len(provider.calls) == 2
    state = session_state.read_state("s1", state_root)
    assert state[codex_luna.STATE_KEY] == ["turn-1"]
    assert codex_luna.RETRY_KEY not in state
    assert codex_luna.FAILED_KEY not in state or not state[codex_luna.FAILED_KEY]


def test_codex_stop_active_inflight_reservation_blocks_until_expiry(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    source = tmp_path / "note.md"
    source.write_text("A short document.\n", encoding="utf-8")
    now = 1000.0
    session_state.write_state(
        "s1",
        {
            "turn_id": "turn-1",
            codex_luna.IN_FLIGHT_KEY: [{
                "turn_id": "turn-1", "token": "live", "created_at": now, "expires_at": now + 60,
            }],
        },
        state_root,
    )
    claude_journal.record_edit("s1", "turn-1", "tool-1", source, state_root=state_root)
    provider = Provider(_result(ReviewKind.DOCUMENT))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(codex_luna.time, "time", lambda: now)
        response = stop.run({"session_id": "s1", "stop_hook_active": True, "cwd": str(tmp_path)}, config, provider=provider)

    assert response["decision"] == "block"
    assert "in progress" in response["reason"]
    assert not provider.calls


def test_codex_stop_reclaims_stale_inflight_reservation_and_reviews(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    config = {"state_root": str(state_root), "ledger_root": str(tmp_path / "ledger")}
    source = tmp_path / "note.md"
    source.write_text("A short document.\n", encoding="utf-8")
    now = 1000.0
    session_state.write_state(
        "s1",
        {
            "turn_id": "turn-1",
            codex_luna.IN_FLIGHT_KEY: [{
                "turn_id": "turn-1", "token": "dead", "created_at": now - 120, "expires_at": now - 1,
            }],
        },
        state_root,
    )
    claude_journal.record_edit("s1", "turn-1", "tool-1", source, state_root=state_root)
    provider = Provider(_result(ReviewKind.DOCUMENT))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(codex_luna.time, "time", lambda: now)
        response = stop.run({"session_id": "s1", "stop_hook_active": True, "cwd": str(tmp_path)}, config, provider=provider)

    assert response == {}
    assert len(provider.calls) == 1
    state = session_state.read_state("s1", state_root)
    assert state[codex_luna.STATE_KEY] == ["turn-1"]
    assert not state.get(codex_luna.IN_FLIGHT_KEY)


def test_session_end_always_fails_open_and_best_effort_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = {"state_root": str(tmp_path / "state")}
    assert session_end.run({}, config) == {}
    session_state.write_state("s1", {codex_luna.RETRY_KEY: "turn-1"}, config["state_root"])
    monkeypatch.setattr(session_end.session_state, "release_session_lease", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read only")))
    assert session_end.run({"session_id": "s1"}, config) == {}
    assert codex_luna.RETRY_KEY not in session_state.read_state("s1", config["state_root"])


def test_bounded_current_session_ledger_read_does_not_call_full_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger"
    for index in range(100):
        reporting.append_row({"session_id": "other", "turn_id": str(index), "event": "edit"}, ledger)
    reporting.append_row({"session_id": "s1", "turn_id": "turn-1", "event": "edit", "path": "a.py"}, ledger)
    monkeypatch.setattr(reporting, "read_jsonl", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full read")))

    rows = reporting.read_session_turn("s1", "turn-1", ledger)

    assert rows == [{"session_id": "s1", "turn_id": "turn-1", "event": "edit", "path": "a.py"}]


def test_async_finding_dedup_uses_session_turn_rule_canonical_path_and_content_hash() -> None:
    left = {"session_id": "s1", "turn_id": "t1", "rule": "r", "path": "./a.py", "content_hash": "same"}
    alias = {"session_id": "s1", "turn_id": "t1", "rule": "r", "path": "a.py", "content_hash": "same"}
    changed = {"session_id": "s1", "turn_id": "t1", "rule": "r", "path": "a.py", "content_hash": "changed"}

    assert reporting._deduplicated([left, alias, changed], {"session_id": "s1", "turn_id": "t1"}) == [left, changed]


def test_every_serialized_hook_message_is_individually_capped() -> None:
    from lib import hookio

    payload = {
        "systemMessage": "s" * 50_000,
        "reason": "r" * 50_000,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "c" * 50_000,
            "permissionDecisionReason": "p" * 50_000,
        },
    }

    serialized = json.dumps(hookio._bounded_payload(payload), ensure_ascii=True, separators=(",", ":"))
    assert len(serialized.encode("utf-8")) <= hookio.MAX_RESPONSE_BYTES
    decoded = json.loads(serialized)
    assert len(decoded["systemMessage"]) <= hookio.MAX_MESSAGE_BYTES
    assert len(decoded["reason"]) <= hookio.MAX_MESSAGE_BYTES
