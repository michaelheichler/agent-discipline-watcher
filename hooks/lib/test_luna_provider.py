from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat

import pytest

from lib import luna_provider, luna_storage
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
    close_calls: int = 0

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

    def close(self) -> None:
        self.close_calls += 1


@dataclass
class FakeSdk:
    session: FakeSession
    launches: list[SdkLaunch] = field(default_factory=list)
    auth_stats: list[os.stat_result | None] = field(default_factory=list)
    config_texts: list[str] = field(default_factory=list)
    cwd_was_empty: list[bool] = field(default_factory=list)
    attempts: int = 0

    def open(self, launch: SdkLaunch) -> FakeSession:
        self.launches.append(launch)
        try:
            self.auth_stats.append((launch.codex_home / "auth.json").stat())
        except FileNotFoundError:
            self.auth_stats.append(None)
        self.config_texts.append((launch.codex_home / "config.toml").read_text(encoding="utf-8"))
        self.cwd_was_empty.append(launch.cwd.is_dir() and not tuple(launch.cwd.iterdir()))
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
    assert sdk.cwd_was_empty == [True]
    turn = sdk.session.threads[0].turns[0]
    assert turn.model == "gpt-5.6-luna"
    assert turn.effort == "high"
    assert turn.sandbox is Sandbox.READ_ONLY
    assert turn.approval_mode is ApprovalMode.DENY_ALL
    assert turn.output_schema["additionalProperties"] is False
    assert turn.output_schema["properties"]["items"]["items"]["additionalProperties"] is False
    assert "Judge only the named pattern" in turn.prompt


def test_comment_prompt_carries_comment_label_rubric(tmp_path: Path) -> None:
    response = '{"items":[{"index":0,"verdict":"states_why","reason":"constraint first"}]}'
    judge, sdk = _judge(tmp_path, (_result(response),))

    judge.judge(JudgeRequest(review_kind=ReviewKind.COMMENT, candidates=("Kept for callers.",)))

    prompt = sdk.session.threads[0].turns[0].prompt
    assert "describes_code" in prompt
    assert "states_why" in prompt


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
    assert sdk.session.close_calls == 1
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


def test_child_environment_strips_provider_credentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(luna_provider.os, "environ", {
        "OPENAI_API_KEY": "must-not-pass",
        "ANTHROPIC_API_KEY": "must-not-pass",
        "PYTHONHOME": "/ambient/python",
        "PYTHONPATH": "/ambient/modules",
        "DYLD_INSERT_LIBRARIES": "/ambient/inject.dylib",
        "UNRELATED_SECRET": "must-not-pass",
        "PATH": "/bin",
        "LANG": "C.UTF-8",
    })

    environment = luna_provider._child_environment(tmp_path / "codex-home")

    assert environment == {
        "PATH": "/bin",
        "LANG": "C.UTF-8",
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "PYTHONPATH": str(Path(luna_provider.__file__).parents[1]),
    }


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


def test_runtime_home_contains_only_minimal_config_and_verified_auth_hard_link(tmp_path: Path) -> None:
    auth = tmp_path / "source-auth.json"
    auth.write_text("secret", encoding="utf-8")
    judge, sdk = _judge(tmp_path)
    judge = LunaJudge(sdk=sdk, runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache", auth_source=auth)

    judge.judge(_request())

    codex_home = sdk.launches[0].codex_home
    assert sdk.auth_stats[0] is not None
    assert stat.S_ISREG(sdk.auth_stats[0].st_mode)
    assert (sdk.auth_stats[0].st_dev, sdk.auth_stats[0].st_ino) == (auth.stat().st_dev, auth.stat().st_ino)
    assert sdk.config_texts[0] == (
        'web_search = "disabled"\n\n[features]\napps = false\nshell_tool = false\n\n[agents]\nenabled = false\n\n[apps._default]\nenabled = false\n\n[mcp_servers]\n'
    )
    assert not codex_home.exists()


def test_each_call_uses_a_fresh_runtime_and_cleans_it_afterward(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path, (_result(), _result()))

    judge.judge(_request())
    judge.judge(_request(rubric_version="adw-rubric-v2"))

    homes = [launch.codex_home for launch in sdk.launches]
    cwds = [launch.cwd for launch in sdk.launches]
    assert homes[0] != homes[1]
    assert cwds[0] != cwds[1]
    assert all(not path.exists() for path in homes + cwds)


def test_auth_source_leaf_swap_fails_closed_and_cleans_runtime(tmp_path: Path, monkeypatch) -> None:
    auth = tmp_path / "source-auth.json"
    replacement = tmp_path / "replacement-auth.json"
    auth.write_text("original", encoding="utf-8")
    replacement.write_text("replacement", encoding="utf-8")
    judge, sdk = _judge(tmp_path)
    judge = LunaJudge(
        sdk=sdk, runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache", auth_source=auth,
    )
    real_link = luna_storage.os.link

    def swap_then_link(source, destination, *, src_dir_fd, dst_dir_fd, follow_symlinks):
        auth.unlink()
        replacement.rename(auth)
        return real_link(
            source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(luna_storage.os, "link", swap_then_link)

    with pytest.raises(LunaProviderFailure, match="changed while linking"):
        judge.judge(_request())

    assert sdk.launches == []
    assert not tuple((tmp_path / "runtime").iterdir())


def test_runtime_directory_swap_fails_closed_without_touching_target(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime = tmp_path / "runtime"
    cache = tmp_path / "cache"
    real_mkdir = luna_storage.os.mkdir
    swapped = False

    def mkdir_then_swap(path, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        result = real_mkdir(path, mode, dir_fd=dir_fd)
        if path == "runtime" and not swapped:
            swapped = True
            runtime.rename(tmp_path / "displaced-runtime")
            runtime.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(luna_storage.os, "mkdir", mkdir_then_swap)
    judge = LunaJudge(
        sdk=_judge(tmp_path)[1], runtime_root=runtime, cache_root=cache,
        auth_source=tmp_path / "missing-auth.json",
    )

    with pytest.raises(LunaProviderFailure, match="directory"):
        judge.judge(_request())

    assert not tuple(outside.iterdir())


def test_cache_fifo_is_rejected_before_provider_execution(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path)
    request = _request()
    cache_path = judge._cache_path(judge._cache_key(request))
    cache_path.parent.mkdir()
    os.mkfifo(cache_path)

    with pytest.raises(LunaProviderFailure, match="regular file"):
        judge.judge(request)

    assert sdk.launches == []
    assert stat.S_ISFIFO(cache_path.lstat().st_mode)


def test_worker_result_requires_exact_provider_identity(tmp_path: Path) -> None:
    judge, _sdk = _judge(tmp_path)
    request = _request()
    result = {
        "payload": {"items": [{"index": 0, "verdict": "violating", "reason": "named pattern"}]},
        "provider": "other-provider",
        "model": "gpt-5.6-luna",
        "effort": "high",
        "rubric_version": request.rubric_version,
        "usage": {},
        "cached": False,
    }

    with pytest.raises(LunaProviderFailure) as error:
        judge._validate_worker_result(request, result)
    assert error.value.category == "worker_protocol"


@pytest.mark.parametrize(
    "field,value",
    (
        ("provider", 1),
        ("model", None),
        ("effort", True),
        ("rubric_version", []),
        ("cached", 0),
        ("cached", "false"),
        ("cached", True),
    ),
)
def test_worker_result_rejects_wrong_scalar_types(tmp_path: Path, field: str, value: object) -> None:
    judge, _sdk = _judge(tmp_path)
    request = _request()
    result = {
        "payload": {"items": [{"index": 0, "verdict": "violating", "reason": "named pattern"}]},
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "effort": "high",
        "rubric_version": request.rubric_version,
        "usage": {},
        "cached": False,
    }
    result[field] = value

    with pytest.raises(LunaProviderFailure) as error:
        judge._validate_worker_result(request, result)
    assert error.value.category == "worker_protocol"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("payload", []),
        ("payload", {"items": [{"index": "0", "verdict": "violating", "reason": "named pattern"}]}),
        ("usage", []),
        ("usage", "tokens"),
    ),
)
def test_worker_result_rejects_malformed_payload_and_usage(
    tmp_path: Path, field: str, value: object,
) -> None:
    judge, _sdk = _judge(tmp_path)
    request = _request()
    result = {
        "payload": {"items": [{"index": 0, "verdict": "violating", "reason": "named pattern"}]},
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "effort": "high",
        "rubric_version": request.rubric_version,
        "usage": {},
        "cached": False,
    }
    result[field] = value

    with pytest.raises(LunaProviderFailure) as error:
        judge._validate_worker_result(request, result)
    assert error.value.category == "worker_protocol"


def test_worker_result_requires_complete_candidate_indexes(tmp_path: Path) -> None:
    judge, _sdk = _judge(tmp_path)
    request = JudgeRequest(
        review_kind=ReviewKind.PATTERN,
        candidates=("first", "second"),
        rule_name="ai_closer",
        rule_action="End when done.",
    )
    result = {
        "payload": {"items": [{"index": 0, "verdict": "violating", "reason": "named pattern"}]},
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "effort": "high",
        "rubric_version": request.rubric_version,
        "usage": {},
        "cached": False,
    }

    with pytest.raises(LunaProviderFailure) as error:
        judge._validate_worker_result(request, result)
    assert error.value.category == "worker_protocol"


def test_auth_device_is_rejected_before_provider_execution(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path)
    judge = LunaJudge(
        sdk=sdk, runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache",
        auth_source=Path("/dev/null"),
    )

    with pytest.raises(LunaProviderFailure, match="regular file"):
        judge.judge(_request())

    assert sdk.launches == []


def test_cache_metadata_mismatch_unlinks_leaf_before_provider_execution(tmp_path: Path) -> None:
    judge, sdk = _judge(tmp_path)
    request = _request()
    cache_path = judge._cache_path(judge._cache_key(request))
    cache_path.parent.mkdir()
    cache_path.write_text(
        '{"payload":{"items":[{"index":0,"verdict":"violating","reason":"stale"}]},'
        '"provider":"wrong-provider","model":"gpt-5.6-luna","effort":"high",'
        '"rubric_version":"adw-rubric-v1","usage":{},"cached":false}',
        encoding="utf-8",
    )
    real_open = sdk.open

    def assert_cache_removed(launch):
        assert not cache_path.exists()
        return real_open(launch)

    sdk.open = assert_cache_removed

    result = judge.judge(request)

    assert result.cached is False
