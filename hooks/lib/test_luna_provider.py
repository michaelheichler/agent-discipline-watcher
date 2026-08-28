from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import time

import pytest

from lib import luna_provider
from lib.judge_contracts import JudgeRequest, ReviewKind
from lib.luna_provider import (
    ApprovalMode,
    LunaJudge,
    LunaProviderFailure,
    OpenAICodexSdk,
    Sandbox,
    SdkAccount,
    SdkItem,
    SdkLaunch,
    SdkModel,
    SdkRunResult,
    SdkThreadStart,
    SdkTurn,
)


VALID_RESPONSE = '{"items":[{"index":0,"verdict":"violating","reason":"matches the named pattern"}]}'


class RetryableFakeError(RuntimeError):
    pass


@dataclass
class FakeThread:
    results: deque[SdkRunResult | BaseException]
    turns: list[SdkTurn] = field(default_factory=list)

    def run(self, turn: SdkTurn) -> SdkRunResult:
        self.turns.append(turn)
        result = self.results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result


@dataclass
class FakeSession:
    account_state: SdkAccount | None
    models_state: tuple[SdkModel, ...]
    results: deque[SdkRunResult | BaseException]
    starts: list[SdkThreadStart] = field(default_factory=list)
    threads: list[FakeThread] = field(default_factory=list)

    def account(self) -> SdkAccount | None:
        return self.account_state

    def models(self, *, include_hidden: bool) -> tuple[SdkModel, ...]:
        assert include_hidden is True
        return self.models_state

    def thread_start(self, start: SdkThreadStart) -> FakeThread:
        self.starts.append(start)
        thread = FakeThread(self.results)
        self.threads.append(thread)
        return thread


@dataclass
class FakeSdk:
    session: FakeSession
    launches: list[SdkLaunch] = field(default_factory=list)
    attempts: int = 0

    def open(self, launch: SdkLaunch) -> FakeSession:
        self.launches.append(launch)
        return self.session

    def retry_on_overload(self, operation, *, max_attempts: int):
        for attempt in range(max_attempts):
            self.attempts += 1
            try:
                return operation()
            except RetryableFakeError:
                if attempt + 1 == max_attempts:
                    raise
        raise AssertionError("unreachable")

    def is_retryable_error(self, error: BaseException) -> bool:
        return isinstance(error, RetryableFakeError)


def _model(*, hidden: bool = False, efforts: tuple[str, ...] = ("low", "high")) -> SdkModel:
    return SdkModel(id="gpt-5.6-luna", model="gpt-5.6-luna", hidden=hidden, supported_reasoning_efforts=efforts)


def _result(
    response: str = VALID_RESPONSE,
    *,
    items: tuple[SdkItem, ...] = (SdkItem("agentMessage"),),
) -> SdkRunResult:
    return SdkRunResult(final_response=response, items=items, usage={"total_tokens": 17, "output_tokens": 9})


def _judge(tmp_path: Path, results: tuple[SdkRunResult | BaseException, ...] = (_result(),), *, account: SdkAccount | None = SdkAccount("chatgpt"), models: tuple[SdkModel, ...] | None = None) -> tuple[LunaJudge, FakeSdk]:
    session = FakeSession(account, (_model(),) if models is None else models, deque(results))
    sdk = FakeSdk(session)
    return LunaJudge(sdk=sdk, runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache", auth_source=tmp_path / "codex-auth.json"), sdk


def _request(*, rubric_version: str = "adw-rubric-v1") -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind.PATTERN,
        candidates=("I hope this helps.",),
        rule_name="ai_closer",
        rule_action="End when the answer is done.",
        rubric_version=rubric_version,
    )


def test_luna_judge_uses_the_subscription_protocol_and_returns_usage(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path)

    result = judge.judge(_request())

    assert result.payload["items"][0]["verdict"] == "violating"
    assert result.usage == {"total_tokens": 17, "output_tokens": 9}
    assert result.model == "gpt-5.6-luna"
    assert sdk.launches[0].config_overrides == (
        "features.apps=false", "apps._default.enabled=false", "web_search=\"disabled\"",
        "features.shell_tool=false", "agents.enabled=false",
    )
    start = sdk.session.starts[0]
    assert start.model == "gpt-5.6-luna"
    assert start.ephemeral is True
    assert start.sandbox is Sandbox.READ_ONLY
    assert start.approval_mode is ApprovalMode.DENY_ALL
    assert start.cwd.is_dir() and not tuple(start.cwd.iterdir())
    turn = sdk.session.threads[0].turns[0]
    assert turn.model == "gpt-5.6-luna"
    assert turn.effort == "high"
    assert turn.sandbox is Sandbox.READ_ONLY
    assert turn.approval_mode is ApprovalMode.DENY_ALL
    assert turn.output_schema["additionalProperties"] is False
    assert turn.output_schema["properties"]["items"]["items"]["additionalProperties"] is False
    assert "Judge only the named pattern" in turn.prompt
    assert "Judge only the named pattern" in turn.prompt


def test_missing_chatgpt_subscription_reports_login_without_starting_a_thread(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, account=None)

    with pytest.raises(LunaProviderFailure, match="ChatGPT.*browser.*device-code"):
        judge.judge(_request())

    assert sdk.session.starts == []


def test_luna_must_be_visible_and_advertise_high_effort(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, models=(_model(hidden=True),))

    with pytest.raises(LunaProviderFailure, match="unavailable"):
        judge.judge(_request())

    assert sdk.session.starts == []


def test_malformed_result_is_rejected_without_cache_entry(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (_result("not json"),))

    with pytest.raises(LunaProviderFailure, match="malformed"):
        judge.judge(_request())

    assert sdk.session.threads[0].turns
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_only_overload_failures_are_retried(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (RetryableFakeError("busy"), _result()))

    result = judge.judge(_request())

    assert result.cached is False
    assert sdk.attempts == 2


def test_transport_failures_are_not_retried_or_cached(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (RuntimeError("transport closed"),))

    with pytest.raises(RuntimeError, match="transport closed"):
        judge.judge(_request())

    assert sdk.attempts == 1
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_cache_hit_skips_the_provider_and_rubric_change_misses(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (_result(), _result()))

    first = judge.judge(_request())
    hit = judge.judge(_request())
    changed = judge.judge(_request(rubric_version="adw-rubric-v2"))

    assert first.cached is False
    assert hit.cached is True
    assert changed.cached is False
    assert len(sdk.session.starts) == 2


def test_document_review_uses_the_same_cache_contract(tmp_path: Path) -> None:
    document_response = '{"notes":[{"quote":"A claim.","problem":"Weak bridge.","fix":"Name the connection."}]}'
    judge, sdk = _judge(tmp_path, (_result(document_response),))
    request = JudgeRequest(
        review_kind=ReviewKind.DOCUMENT,
        source_context="A claim.",
        rubric_version="adw-rubric-v1",
    )

    first = judge.judge(request)
    hit = judge.judge(request)

    assert first.cached is False
    assert hit.cached is True
    assert len(sdk.session.starts) == 1


def test_invalid_cache_payload_is_not_returned_as_a_judgment(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (_result(), _result()))
    request = _request()
    judge.judge(request)
    cache_path = judge._cache_path(judge._cache_key(request))
    cache_path.write_text(
        '{"payload":{"items":[{"index":"wrong"}]},"provider":"openai-codex","model":"gpt-5.6-luna","effort":"high","rubric_version":"adw-rubric-v1","usage":{},"cached":false}',
        encoding="utf-8",
    )

    result = judge.judge(request)

    assert result.cached is False
    assert len(sdk.session.starts) == 2


@pytest.mark.parametrize("item_type", ("commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "toolSearchCall", "collabAgentToolCall", "subAgentActivity"))
def test_tool_items_are_rejected_and_never_cached(tmp_path: Path, item_type: str) -> None:
    judge, _sdk = _judge(tmp_path, (_result(items=(SdkItem(item_type),)),))

    with pytest.raises(LunaProviderFailure, match="tool"):
        judge.judge(_request())

    assert list((tmp_path / "cache").glob("*.json")) == []


def test_document_prompt_carries_the_existing_document_rubric(tmp_path: Path) -> None:
    document_response = '{"notes":[]}'
    judge, sdk = _judge(tmp_path, (_result(document_response),))

    judge.judge(JudgeRequest(review_kind=ReviewKind.DOCUMENT, source_context="A document."))

    prompt = sdk.session.threads[0].turns[0].prompt
    assert "Coherence:" in prompt
    assert "Quote the sentence" in prompt


def test_rejected_partial_indexes_are_not_cached(tmp_path: Path) -> None:
    partial = '{"items":[{"index":0,"verdict":"violating","reason":"only one"}]}'
    judge, _sdk = _judge(tmp_path, (_result(partial),))
    request = JudgeRequest(
        review_kind=ReviewKind.PATTERN,
        candidates=("first", "second"),
        rule_name="ai_closer",
        rule_action="End when done.",
    )

    with pytest.raises(LunaProviderFailure, match="malformed"):
        judge.judge(request)

    assert list((tmp_path / "cache").glob("*.json")) == []


def test_overload_exhaustion_stops_after_exactly_three_attempts(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (RetryableFakeError("busy"),) * 3)

    with pytest.raises(RetryableFakeError, match="busy"):
        judge.judge(_request())

    assert sdk.attempts == 3


def test_lifecycle_timeout_covers_sdk_startup(tmp_path: Path, monkeypatch) -> None:
    judge, sdk = _judge(tmp_path)
    original_open = sdk.open

    def delayed_open(launch):
        time.sleep(0.05)
        return original_open(launch)

    monkeypatch.setattr(sdk, "open", delayed_open)
    monkeypatch.setattr(luna_provider, "JUDGE_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(LunaProviderFailure, match="timed out"):
        judge.judge(_request())


def test_child_environment_strips_provider_credentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-pass")
    monkeypatch.setenv("PATH", "/bin")

    environment = luna_provider._child_environment(tmp_path / "codex-home")

    assert "OPENAI_API_KEY" not in environment
    assert "ANTHROPIC_API_KEY" not in environment
    assert environment["PATH"] == "/bin"
    assert environment["CODEX_HOME"] == str(tmp_path / "codex-home")


def test_runtime_symlink_fails_closed_without_touching_its_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(outside, target_is_directory=True)
    judge, _sdk = _judge(tmp_path)
    judge = LunaJudge(sdk=judge._sdk, runtime_root=runtime, cache_root=tmp_path / "cache", auth_source=tmp_path / "missing")

    with pytest.raises(LunaProviderFailure, match="symlink"):
        judge.judge(_request())

    assert not tuple(outside.iterdir())


def test_cache_symlink_fails_closed_without_reading_its_target(tmp_path: Path) -> None:
    judge, _sdk = _judge(tmp_path)
    cache = tmp_path / "cache"
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    cache.symlink_to(outside)

    with pytest.raises(LunaProviderFailure, match="symlink"):
        judge.judge(_request())

    assert outside.read_text(encoding="utf-8") == "outside"


def test_runtime_home_contains_only_minimal_config_and_auth_symlink(tmp_path: Path) -> None:
    auth = tmp_path / "source-auth.json"
    auth.write_text("secret", encoding="utf-8")
    judge, sdk = _judge(tmp_path)
    judge = LunaJudge(sdk=sdk, runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache", auth_source=auth)

    judge.judge(_request())

    codex_home = sdk.launches[0].codex_home
    assert (codex_home / "auth.json").is_symlink()
    assert (codex_home / "auth.json").resolve() == auth
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        'web_search = "disabled"\n\n[features]\napps = false\nshell_tool = false\n\n[agents]\nenabled = false\n\n[apps._default]\nenabled = false\n\n[mcp_servers]\n'
    )


def test_runtime_home_drops_a_stale_auth_copy_when_no_source_exists(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path)
    stale_auth = tmp_path / "runtime" / "codex-judge" / "home" / "auth.json"
    stale_auth.parent.mkdir(parents=True)
    stale_auth.write_text("never retain copied credentials", encoding="utf-8")

    judge.judge(_request())

    assert not (sdk.launches[0].codex_home / "auth.json").exists()
