from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from hashlib import sha256
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Protocol, cast

from .judge_contracts import JudgeRequest, JudgeResult, build_prompt, content_hash, output_schema, validate_payload
from .luna_runtime import require_runtime
from .luna_process import child_environment as _child_environment
from .luna_process import sdk_environment as _sdk_environment
from .luna_process import terminate_process_group as _terminate_process_group
from .luna_sdk import enum_value as _enum_value
from .luna_sdk import item_type as _item_type
from .luna_sdk import usage_dict as _usage_dict
from .luna_storage import LunaProviderFailure, RuntimePaths, SecureJudgeStorage
from .luna_validation import parse_luna_version, validate_candidate_indexes, validate_worker_result
from .luna_worker_protocol import request_payload, response_result


LUNA_MODEL = "gpt-6-luna"
LUNA_MODEL_MEMO_NAME = "luna-model"
LUNA_EFFORT = "high"
PROVIDER_NAME = "openai-codex"
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
JUDGE_TIMEOUT_SECONDS = 105
MAX_TIMEOUT_SECONDS = 24 * 60 * 60
MAX_OVERLOAD_ATTEMPTS = 3
CONFIG_OVERRIDES = (
    "features.apps=false",
    "apps._default.enabled=false",
    'web_search="disabled"',
    "features.shell_tool=false",
    "agents.enabled=false",
)
MINIMAL_CONFIG = (
    'web_search = "disabled"\n\n'
    "[features]\napps = false\nshell_tool = false\n\n"
    "[agents]\nenabled = false\n\n"
    "[apps._default]\nenabled = false\n\n"
    "[mcp_servers]\n"
)
BASE_INSTRUCTIONS = "You are the ADW judge. Inspect only supplied review context."
DEVELOPER_INSTRUCTIONS = "Return only the requested JSON object; do not modify files or use tools."
SAFE_ITEM_TYPES = frozenset({
    "userMessage", "agentMessage", "reasoning", "plan", "contextCompaction",
})


Sandbox = SimpleNamespace(READ_ONLY="read_only")
ApprovalMode = SimpleNamespace(DENY_ALL="deny_all")


@dataclass(frozen=True)
class SdkAccount:
    root_type: str | None


@dataclass(frozen=True)
class SdkModel:
    id: str | None
    model: str | None
    hidden: bool
    supported_reasoning_efforts: tuple[str, ...]


@dataclass(frozen=True)
class SdkItem:
    type: str


@dataclass(frozen=True)
class SdkRunResult:
    final_response: str | None
    items: tuple[SdkItem, ...]
    usage: dict[str, Any]


@dataclass(frozen=True)
class SdkLaunch:
    codex_home: Path
    cwd: Path
    config_overrides: tuple[str, ...]
    call_fd: int | None = None
    codex_home_fd: int | None = None
    cwd_fd: int | None = None
    call_identity: tuple[int, int] | None = None
    codex_home_identity: tuple[int, int] | None = None
    cwd_identity: tuple[int, int] | None = None


@dataclass(frozen=True)
class SdkThreadStart:
    model: str
    cwd: Path
    ephemeral: bool
    sandbox: str
    approval_mode: str
    base_instructions: str
    developer_instructions: str


@dataclass(frozen=True)
class SdkTurn:
    prompt: str
    model: str
    effort: str
    sandbox: str
    approval_mode: str
    output_schema: dict[str, Any]


class SdkThread(Protocol):
    def run(self, turn: SdkTurn) -> SdkRunResult: ...
    def close(self) -> None: ...


class SdkSession(Protocol):
    def account(self) -> SdkAccount | None: ...
    def models(self, *, include_hidden: bool) -> tuple[SdkModel, ...]: ...
    def thread_start(self, start: SdkThreadStart) -> SdkThread: ...


class CodexSdk(Protocol):
    def open(self, launch: SdkLaunch) -> SdkSession: ...
    def retry_on_overload(self, operation: Callable[[], SdkRunResult], *, max_attempts: int) -> SdkRunResult: ...


class _OpenAICodexThread:
    def __init__(self, thread: object, sandbox: object, approval_mode: object, effort: object) -> None:
        self._thread = thread
        self._sandbox = sandbox
        self._approval_mode = approval_mode
        self._effort = effort

    def run(self, turn: SdkTurn) -> SdkRunResult:
        result = self._thread.run(
            turn.prompt, model=turn.model, effort=self._effort.high,
            sandbox=self._sandbox.read_only, approval_mode=self._approval_mode.deny_all,
            output_schema=turn.output_schema,
        )
        return SdkRunResult(
            final_response=result.final_response,
            items=tuple(SdkItem(_item_type(item)) for item in result.items),
            usage=_usage_dict(result.usage),
        )

    def close(self) -> None:
        close = getattr(self._thread, "close", None)
        if callable(close):
            close()


class _OpenAICodexSession:
    def __init__(self, codex: object, sandbox: object, approval_mode: object, effort: object) -> None:
        self._codex = codex
        self._sandbox = sandbox
        self._approval_mode = approval_mode
        self._effort = effort

    def account(self) -> SdkAccount | None:
        account = self._codex.account().account
        root = getattr(account, "root", None) if account is not None else None
        return None if root is None else SdkAccount(getattr(root, "type", None))

    def models(self, *, include_hidden: bool) -> tuple[SdkModel, ...]:
        rows = self._codex.models(include_hidden=include_hidden).data
        return tuple(
            SdkModel(
                id=getattr(row, "id", None), model=getattr(row, "model", None),
                hidden=bool(getattr(row, "hidden", False)),
                supported_reasoning_efforts=tuple(
                    _enum_value(getattr(option, "reasoning_effort", option))
                    for option in getattr(row, "supported_reasoning_efforts", ())
                ),
            )
            for row in rows
        )

    def thread_start(self, start: SdkThreadStart) -> SdkThread:
        thread = self._codex.thread_start(
            model=start.model, cwd=str(start.cwd), ephemeral=start.ephemeral,
            sandbox=self._sandbox.read_only, approval_mode=self._approval_mode.deny_all,
            base_instructions=start.base_instructions,
            developer_instructions=start.developer_instructions,
        )
        return _OpenAICodexThread(thread, self._sandbox, self._approval_mode, self._effort)

    def close(self) -> None:
        self._codex.close()


class OpenAICodexSdk:
    def open(self, launch: SdkLaunch) -> SdkSession:
        try:
            from openai_codex import ApprovalMode as CodexApprovalMode
            from openai_codex import Codex, CodexConfig, Sandbox as CodexSandbox
            from openai_codex.types import ReasoningEffort
        except ImportError as exc:
            raise LunaProviderFailure(
                "Luna judging needs the openai-codex package and its pinned Codex runtime; reinstall ADW runtime dependencies."
            ) from exc
        codex = Codex(CodexConfig(
            config_overrides=launch.config_overrides,
            cwd=(None if launch.cwd_fd is not None else str(launch.cwd)),
            env=_sdk_environment(launch.codex_home),
        ))
        return _OpenAICodexSession(codex, CodexSandbox, CodexApprovalMode, ReasoningEffort)

    def retry_on_overload(self, operation: Callable[[], SdkRunResult], *, max_attempts: int) -> SdkRunResult:
        try:
            from openai_codex import retry_on_overload
        except ImportError as exc:
            raise LunaProviderFailure("Luna judging needs the openai-codex package; reinstall ADW runtime dependencies.") from exc
        return retry_on_overload(operation, max_attempts=max_attempts)


def _normalized_timeout(timeout_seconds: object) -> float | None:
    if timeout_seconds is None:
        return None
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be finite, positive, and bounded")
    try:
        normalized = float(timeout_seconds)
    except (OverflowError, ValueError) as exc:
        raise ValueError("timeout_seconds must be finite, positive, and bounded") from exc
    if not math.isfinite(normalized) or not 0 < normalized <= MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be finite, positive, and bounded")
    return normalized


def _runtime_launch(runtime: RuntimePaths) -> SdkLaunch:
    """Extracted, since judge() had drifted past the length gate."""
    return SdkLaunch(
        codex_home=runtime.codex_home, cwd=runtime.cwd,
        config_overrides=CONFIG_OVERRIDES,
        call_fd=runtime.call_fd,
        codex_home_fd=runtime.codex_home_fd, cwd_fd=runtime.cwd_fd,
        call_identity=runtime.call_identity,
        codex_home_identity=runtime.codex_home_identity,
        cwd_identity=runtime.cwd_identity,
    )


def _spawn_worker(worker_python: Path, launch: SdkLaunch) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(worker_python), "-m", "lib.luna_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=_child_environment(Path("../home"), Path(__file__).parents[1]),
        start_new_session=True,
        pass_fds=(launch.call_fd, launch.codex_home_fd, launch.cwd_fd),
    )


class LunaJudge:
    def __init__(
        self,
        *,
        sdk: CodexSdk | None = None,
        runtime_root: str | os.PathLike[str] | None = None,
        cache_root: str | os.PathLike[str] | None = None,
        auth_source: str | os.PathLike[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._sdk = sdk or OpenAICodexSdk()
        if (runtime_root is None) != (cache_root is None):
            raise ValueError("runtime_root and cache_root must be supplied together")
        self._default_storage = runtime_root is None
        self._runtime_root = Path(runtime_root) if runtime_root is not None else Path.home() / ".adw" / "runtime"
        self._cache_root = Path(cache_root) if cache_root is not None else Path.home() / ".adw" / "cache" / "judges"
        self._auth_source = Path(auth_source) if auth_source is not None else Path.home() / ".codex" / "auth.json"
        self._timeout_seconds = _normalized_timeout(timeout_seconds)

    @property
    def timeout_seconds(self) -> float | None:
        return self._timeout_seconds

    def judge(self, request: JudgeRequest) -> JudgeResult:
        storage_factory = SecureJudgeStorage if self._default_storage else lambda: SecureJudgeStorage(
            runtime_root=self._runtime_root, cache_root=self._cache_root,
        )
        with storage_factory() as storage:
            remembered_key = self._cache_key(request, self._remembered_model(storage))
            cached = self._read_cache(storage, remembered_key, request)
            if cached is not None:
                return replace(cached, cached=True)
            with storage.runtime(config_text=MINIMAL_CONFIG, auth_source=self._auth_source) as runtime:
                launch = _runtime_launch(runtime)
                if not isinstance(self._sdk, OpenAICodexSdk):
                    result = run_sdk_request(request, launch, self._sdk)
                else:
                    result = self._run_worker(request, launch)
            result = self._validate_worker_result(request, result)
            storage.write_cache(LUNA_MODEL_MEMO_NAME, result.model)
            self._write_cache(storage, self._cache_key(request, result.model), result)
            return result

    @staticmethod
    def _remembered_model(storage: SecureJudgeStorage) -> str:
        """Remembered id, since a stale floor read would miss a moved model."""
        cached = storage.read_cache(LUNA_MODEL_MEMO_NAME)
        if cached is None:
            return LUNA_MODEL
        model = cached[0].strip()
        return model if parse_luna_version(model) is not None else LUNA_MODEL

    def _worker_python(self) -> Path:
        try:
            return require_runtime() if self._default_storage else Path(sys.executable)
        except RuntimeError as exc:
            raise LunaProviderFailure(str(exc), category="configuration") from exc

    def _run_worker(self, request: JudgeRequest, launch: SdkLaunch) -> JudgeResult:
        if not _launch_is_pinned(launch):
            raise LunaProviderFailure(
                "Luna worker requires descriptor-pinned runtime paths", category="configuration",
            )
        timeout_seconds = self._timeout_seconds or JUDGE_TIMEOUT_SECONDS
        deadline = time.monotonic() + timeout_seconds
        worker_python = self._worker_python()
        payload = json.dumps(request_payload(request, launch))
        process = _spawn_worker(worker_python, launch)
        successful = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            communication = cast(tuple[str | None, str | None], process.communicate(payload, timeout=remaining))
            value = self._validate_worker_result(request, response_result(process.returncode, next(iter(communication))))
            successful = True
            return value
        except subprocess.TimeoutExpired as exc:
            raise LunaProviderFailure("Luna judge timed out", category="timeout") from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LunaProviderFailure("Luna worker returned malformed output", category="worker_protocol") from exc
        finally:
            if not successful:
                _terminate_process_group(process)

    @staticmethod
    def _validate_candidate_indexes(request: JudgeRequest, payload: dict[str, Any]) -> None:
        validate_candidate_indexes(request, payload)

    @staticmethod
    def _validate_worker_result(request: JudgeRequest, result: object) -> JudgeResult:
        return validate_worker_result(request, result, PROVIDER_NAME, LUNA_EFFORT)

    def _cache_key(self, request: JudgeRequest, model: str) -> str:
        identity = "|".join((content_hash(request), request.review_kind.value, PROVIDER_NAME, model, LUNA_EFFORT, request.rubric_version))
        return sha256(identity.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_root / f"{key}.json"

    def _read_cache(
        self, storage: SecureJudgeStorage, key: str, request: JudgeRequest,
    ) -> JudgeResult | None:
        name = f"{key}.json"
        try:
            cached = storage.read_cache(name)
            if cached is None:
                return None
            text, metadata = cached
            if metadata.st_mtime < time.time() - CACHE_TTL_SECONDS:
                storage.unlink_cache(name)
                return None
            row = json.loads(text)
            result = self._validate_worker_result(request, row)
            return result
        except (LunaProviderFailure, TypeError, ValueError, json.JSONDecodeError):
            storage.unlink_cache(name)
            return None

    def _write_cache(self, storage: SecureJudgeStorage, key: str, result: JudgeResult) -> None:
        if result.cached is not False:
            raise LunaProviderFailure(
                "Luna judge refused to cache a non-fresh result", category="worker_protocol",
            )
        text = json.dumps(
            {**result.__dict__, "cached": False}, ensure_ascii=True, sort_keys=True,
        )
        storage.write_cache(f"{key}.json", text)


def run_sdk_request(request: JudgeRequest, launch: SdkLaunch, sdk: CodexSdk) -> JudgeResult:
    return sdk.retry_on_overload(
        lambda: _run_sdk_once(request, launch, sdk), max_attempts=MAX_OVERLOAD_ATTEMPTS,
    )


def _run_turn(session: SdkSession, request: JudgeRequest, launch: SdkLaunch) -> tuple[SdkRunResult, str]:
    account = session.account()
    if account is None or account.root_type != "chatgpt":
        raise LunaProviderFailure(
            "Luna judging requires a ChatGPT subscription session. Complete Codex ChatGPT browser login or device-code login, then retry.",
            category="authentication",
        )
    models = session.models(include_hidden=True)
    model_id = _resolve_luna_model(models)
    _validate_luna(models, model_id)
    thread = session.thread_start(SdkThreadStart(
        model=model_id, cwd=launch.cwd, ephemeral=True, sandbox=Sandbox.READ_ONLY,
        approval_mode=ApprovalMode.DENY_ALL, base_instructions=BASE_INSTRUCTIONS,
        developer_instructions=DEVELOPER_INSTRUCTIONS,
    ))
    result = thread.run(SdkTurn(
        prompt=build_prompt(request), model=model_id, effort=LUNA_EFFORT,
        sandbox=Sandbox.READ_ONLY, approval_mode=ApprovalMode.DENY_ALL,
        output_schema=output_schema(request),
    ))
    return result, model_id


def _parsed_payload(request: JudgeRequest, raw: SdkRunResult) -> dict[str, Any]:
    try:
        if not raw.final_response or not raw.final_response.strip():
            raise ValueError("empty final response")
        payload = validate_payload(json.loads(raw.final_response), output_schema(request))
        _validate_candidate_indexes(request, payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LunaProviderFailure(
            f"Luna judge returned malformed structured output: {exc}", category="malformed",
        ) from exc
    return payload


def _run_sdk_once(request: JudgeRequest, launch: SdkLaunch, sdk: CodexSdk) -> JudgeResult:
    session = sdk.open(launch)
    try:
        raw, model_id = _run_turn(session, request, launch)
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    _reject_tool_items(raw.items)
    return JudgeResult(
        payload=_parsed_payload(request, raw), provider=PROVIDER_NAME, model=model_id, effort=LUNA_EFFORT,
        rubric_version=request.rubric_version, usage=raw.usage,
    )


def _resolve_luna_model(models: tuple[SdkModel, ...]) -> str:
    """Highest wins, since a stale floor would hide a newer model."""
    best_id: str | None = None
    best_version: tuple[int, ...] | None = None
    for model in models:
        identifier = model.id or model.model
        if identifier is None or model.hidden or LUNA_EFFORT not in model.supported_reasoning_efforts:
            continue
        version = parse_luna_version(identifier)
        if version is None or best_version is not None and version <= best_version:
            continue
        best_id, best_version = identifier, version
    return best_id or LUNA_MODEL


def _seen_model_ids(models: tuple[SdkModel, ...]) -> str:
    ids = sorted({identifier for model in models for identifier in (model.id, model.model) if identifier})
    return ", ".join(ids) if ids else "none"


def _validate_luna(models: tuple[SdkModel, ...], resolved_id: str) -> None:
    luna = next((model for model in models if resolved_id in (model.id, model.model)), None)
    if luna is None or luna.hidden:
        raise LunaProviderFailure(
            f"{resolved_id} is unavailable to this Codex account; saw {_seen_model_ids(models)}",
            category="availability",
        )
    if LUNA_EFFORT not in luna.supported_reasoning_efforts:
        raise LunaProviderFailure(
            f"{resolved_id} does not advertise high reasoning effort; saw {_seen_model_ids(models)}",
            category="availability",
        )


def _reject_tool_items(items: tuple[SdkItem, ...]) -> None:
    if any(item.type not in SAFE_ITEM_TYPES for item in items):
        raise LunaProviderFailure("Luna judge used a forbidden tool item", category="policy")


def _validate_candidate_indexes(request: JudgeRequest, payload: dict[str, Any]) -> None:
    validate_candidate_indexes(request, payload)


def _launch_is_pinned(launch: SdkLaunch) -> bool:
    descriptors = (
        launch.call_fd, launch.codex_home_fd, launch.cwd_fd,
        launch.call_identity, launch.codex_home_identity, launch.cwd_identity,
    )
    return all(value is not None for value in descriptors)
