from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from lib.judge_contracts import JudgeRequest, ReviewKind, output_schema
from lib.luna_provider import (
    ApprovalMode,
    CONFIG_OVERRIDES,
    OpenAICodexSdk,
    Sandbox,
    SdkLaunch,
    SdkThreadStart,
    SdkTurn,
)


class OfficialReasoningEffort(Enum):
    low = "low"
    high = "high"


class OfficialSandbox(Enum):
    read_only = "read-only"


class OfficialApprovalMode(Enum):
    deny_all = "never"


class ServerBusyError(RuntimeError):
    pass


@dataclass
class Recorder:
    config: object | None = None
    include_hidden: list[bool] = field(default_factory=list)
    thread_starts: list[dict[str, object]] = field(default_factory=list)
    turns: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    closed: bool = False
    retry_attempts: int = 0


class Usage:
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {
            "last": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            "total": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        }


class ThreadItem:
    def __init__(self, item_type: str) -> None:
        self.root = SimpleNamespace(type=item_type)


def install_official_shaped_module(monkeypatch, recorder: Recorder) -> None:
    module = ModuleType("openai_codex")
    types_module = ModuleType("openai_codex.types")

    class CodexConfig:
        def __init__(self, *, config_overrides, cwd, env) -> None:
            self.config_overrides = config_overrides
            self.cwd = cwd
            self.env = env

    class Thread:
        ephemeral = True

        def run(self, prompt: str, **kwargs):
            recorder.turns.append((prompt, kwargs))
            return SimpleNamespace(
                final_response='{"items":[{"index":0,"verdict":"clean","reason":"specific"}]}',
                items=(ThreadItem("agentMessage"), ThreadItem("reasoning")),
                usage=Usage(),
            )

    class Codex:
        def __init__(self, config: CodexConfig) -> None:
            recorder.config = config

        def account(self):
            return SimpleNamespace(account=SimpleNamespace(root=SimpleNamespace(type="chatgpt")))

        def models(self, *, include_hidden: bool):
            recorder.include_hidden.append(include_hidden)
            effort = SimpleNamespace(reasoning_effort=OfficialReasoningEffort.high)
            model = SimpleNamespace(
                id="gpt-5.6-luna", model="gpt-5.6-luna", hidden=False,
                supported_reasoning_efforts=(effort,),
            )
            return SimpleNamespace(data=(model,))

        def thread_start(self, **kwargs):
            recorder.thread_starts.append(kwargs)
            return Thread()

        def close(self) -> None:
            recorder.closed = True

    def retry_on_overload(operation, *, max_attempts: int):
        for attempt in range(max_attempts):
            recorder.retry_attempts += 1
            try:
                return operation()
            except ServerBusyError:
                if attempt + 1 == max_attempts:
                    raise
        raise AssertionError("unreachable")

    module.ApprovalMode = OfficialApprovalMode
    module.Codex = Codex
    module.CodexConfig = CodexConfig
    module.Sandbox = OfficialSandbox
    module.ServerBusyError = ServerBusyError
    module.retry_on_overload = retry_on_overload
    types_module.ReasoningEffort = OfficialReasoningEffort
    monkeypatch.setitem(sys.modules, "openai_codex", module)
    monkeypatch.setitem(sys.modules, "openai_codex.types", types_module)


def test_openai_codex_adapter_uses_official_shapes_and_minimal_config(
    tmp_path: Path, monkeypatch,
) -> None:
    recorder = Recorder()
    install_official_shaped_module(monkeypatch, recorder)
    monkeypatch.setattr(
        "lib.luna_provider.os.environ",
        {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "TMPDIR": str(tmp_path / "tmp"),
            "PYTHONHOME": "/ambient/python",
            "PYTHONPATH": "/ambient/modules",
            "DYLD_INSERT_LIBRARIES": "/ambient/inject.dylib",
            "OPENAI_API_KEY": "must-not-pass",
            "ANTHROPIC_API_KEY": "must-not-pass",
            "UNRELATED_SECRET": "must-not-pass",
        },
    )
    launch = SdkLaunch(
        codex_home=tmp_path / "home", cwd=tmp_path / "cwd",
        config_overrides=CONFIG_OVERRIDES,
    )
    request = JudgeRequest(
        review_kind=ReviewKind.PATTERN, candidates=("candidate",),
        rule_name="named-pattern", rule_action="remove it",
    )
    sdk = OpenAICodexSdk()

    session = sdk.open(launch)
    account = session.account()
    models = session.models(include_hidden=True)
    thread = session.thread_start(SdkThreadStart(
        model="gpt-5.6-luna", cwd=launch.cwd, ephemeral=True,
        sandbox=Sandbox.READ_ONLY, approval_mode=ApprovalMode.DENY_ALL,
        base_instructions="base", developer_instructions="developer",
    ))
    result = thread.run(SdkTurn(
        prompt="judge", model="gpt-5.6-luna", effort="high",
        sandbox=Sandbox.READ_ONLY, approval_mode=ApprovalMode.DENY_ALL,
        output_schema=output_schema(request),
    ))
    session.close()

    assert account is not None and account.root_type == "chatgpt"
    assert models[0].supported_reasoning_efforts == ("high",)
    assert recorder.include_hidden == [True]
    assert recorder.config is not None
    assert recorder.config.config_overrides == CONFIG_OVERRIDES
    assert recorder.config.cwd == str(launch.cwd)
    assert recorder.config.env == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp_path / "tmp"),
        "CODEX_HOME": str(launch.codex_home),
    }
    assert recorder.thread_starts == [{
        "model": "gpt-5.6-luna", "cwd": str(launch.cwd), "ephemeral": True,
        "sandbox": OfficialSandbox.read_only,
        "approval_mode": OfficialApprovalMode.deny_all,
        "base_instructions": "base", "developer_instructions": "developer",
    }]
    assert recorder.turns[0][1] == {
        "model": "gpt-5.6-luna", "effort": OfficialReasoningEffort.high,
        "sandbox": OfficialSandbox.read_only,
        "approval_mode": OfficialApprovalMode.deny_all,
        "output_schema": output_schema(request),
    }
    assert result.final_response is not None
    assert [item.type for item in result.items] == ["agentMessage", "reasoning"]
    assert result.usage == {
        "last": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        "total": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
    }
    assert recorder.closed is True


def test_openai_codex_adapter_retries_exactly_three_times_then_exhausts(monkeypatch) -> None:
    recorder = Recorder()
    install_official_shaped_module(monkeypatch, recorder)
    sdk = OpenAICodexSdk()

    def overloaded():
        raise ServerBusyError("busy")

    with pytest.raises(ServerBusyError, match="busy"):
        sdk.retry_on_overload(overloaded, max_attempts=3)

    assert recorder.retry_attempts == 3
