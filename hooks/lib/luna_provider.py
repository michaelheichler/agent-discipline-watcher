"""Subscription-backed Luna judge behind an ADW-owned SDK boundary."""
from __future__ import annotations

import json
import os
import signal
import stat
import tempfile
import threading
import time
from hashlib import sha256
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol

from .judge_contracts import JudgeRequest, JudgeResult, build_prompt, content_hash, output_schema, validate_payload
from .session_state import plugin_data_home


LUNA_MODEL = "gpt-5.6-luna"
LUNA_EFFORT = "high"
PROVIDER_NAME = "openai-codex"
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
JUDGE_TIMEOUT_SECONDS = 120
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


class LunaProviderFailure(RuntimeError):
    pass


class Sandbox:
    READ_ONLY = "read_only"


class ApprovalMode:
    DENY_ALL = "deny_all"


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
    """The sole production import point for the official openai-codex SDK."""

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
            cwd=str(launch.cwd), env=_child_environment(launch.codex_home),
        ))
        return _OpenAICodexSession(codex, CodexSandbox, CodexApprovalMode, ReasoningEffort)

    def retry_on_overload(self, operation: Callable[[], SdkRunResult], *, max_attempts: int) -> SdkRunResult:
        try:
            from openai_codex import retry_on_overload
        except ImportError as exc:
            raise LunaProviderFailure("Luna judging needs the openai-codex package; reinstall ADW runtime dependencies.") from exc
        return retry_on_overload(operation, max_attempts=max_attempts)


class LunaJudge:
    def __init__(
        self,
        *,
        sdk: CodexSdk | None = None,
        runtime_root: str | os.PathLike[str] | None = None,
        cache_root: str | os.PathLike[str] | None = None,
        auth_source: str | os.PathLike[str] | None = None,
    ) -> None:
        root = plugin_data_home()
        self._sdk = sdk or OpenAICodexSdk()
        self._runtime_root = Path(runtime_root) if runtime_root is not None else root / "runtime"
        self._cache_root = Path(cache_root) if cache_root is not None else root / "cache" / "judges"
        self._auth_source = Path(auth_source) if auth_source is not None else Path.home() / ".codex" / "auth.json"

    def judge(self, request: JudgeRequest) -> JudgeResult:
        _ensure_directory(self._cache_root)
        key = self._cache_key(request)
        cached = self._read_cache(key, request)
        if cached is not None:
            return replace(cached, cached=True)
        result = self._sdk.retry_on_overload(
            lambda: self._run_once(request), max_attempts=MAX_OVERLOAD_ATTEMPTS,
        )
        self._write_cache(key, result)
        return result

    def _run_once(self, request: JudgeRequest) -> JudgeResult:
        with _lifecycle_deadline(JUDGE_TIMEOUT_SECONDS):
            launch = self._prepare_runtime()
            session = self._sdk.open(launch)
            try:
                account = session.account()
                if account is None or account.root_type != "chatgpt":
                    raise LunaProviderFailure(
                        "Luna judging requires a ChatGPT subscription session. Complete Codex ChatGPT browser login or device-code login, then retry."
                    )
                self._validate_luna(session.models(include_hidden=True))
                thread = session.thread_start(SdkThreadStart(
                    model=LUNA_MODEL, cwd=launch.cwd, ephemeral=True, sandbox=Sandbox.READ_ONLY,
                    approval_mode=ApprovalMode.DENY_ALL, base_instructions=BASE_INSTRUCTIONS,
                    developer_instructions=DEVELOPER_INSTRUCTIONS,
                ))
                raw = thread.run(SdkTurn(
                    prompt=build_prompt(request), model=LUNA_MODEL, effort=LUNA_EFFORT,
                    sandbox=Sandbox.READ_ONLY, approval_mode=ApprovalMode.DENY_ALL,
                    output_schema=output_schema(request),
                ))
            finally:
                close = getattr(session, "close", None)
                if callable(close):
                    close()
        self._reject_tool_items(raw.items)
        try:
            if not raw.final_response or not raw.final_response.strip():
                raise ValueError("empty final response")
            payload = validate_payload(json.loads(raw.final_response), output_schema(request))
            self._validate_candidate_indexes(request, payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LunaProviderFailure(f"Luna judge returned malformed structured output: {exc}") from exc
        return JudgeResult(
            payload=payload, provider=PROVIDER_NAME, model=LUNA_MODEL, effort=LUNA_EFFORT,
            rubric_version=request.rubric_version, usage=raw.usage,
        )

    def _prepare_runtime(self) -> SdkLaunch:
        _ensure_directory(self._runtime_root)
        root = self._runtime_root / "codex-judge"
        home = root / "home"
        cwd = root / "cwd"
        _ensure_directory(home)
        _ensure_directory(cwd)
        if any(cwd.iterdir()):
            raise LunaProviderFailure("isolated Luna judge cwd is not empty")
        config = home / "config.toml"
        _write_regular(config, MINIMAL_CONFIG)
        auth = home / "auth.json"
        if _is_regular_file(self._auth_source):
            if auth.is_symlink() and auth.resolve() == self._auth_source.resolve():
                pass
            else:
                auth.unlink(missing_ok=True)
                auth.symlink_to(self._auth_source.resolve())
        elif _path_exists(auth):
            auth.unlink()
        return SdkLaunch(codex_home=home, cwd=cwd, config_overrides=CONFIG_OVERRIDES)

    def _validate_luna(self, models: tuple[SdkModel, ...]) -> None:
        luna = next((model for model in models if model.id == LUNA_MODEL or model.model == LUNA_MODEL), None)
        if luna is None or luna.hidden:
            raise LunaProviderFailure("gpt-5.6-luna is unavailable to this Codex account")
        if LUNA_EFFORT not in luna.supported_reasoning_efforts:
            raise LunaProviderFailure("gpt-5.6-luna does not advertise high reasoning effort")

    @staticmethod
    def _reject_tool_items(items: tuple[SdkItem, ...]) -> None:
        if any(item.type not in SAFE_ITEM_TYPES for item in items):
            raise LunaProviderFailure("Luna judge used a forbidden tool item")

    @staticmethod
    def _validate_candidate_indexes(request: JudgeRequest, payload: dict[str, Any]) -> None:
        rows = payload.get("items")
        if not isinstance(rows, list):
            return
        if [row["index"] for row in rows] != list(range(len(request.candidates))):
            raise ValueError("response indexes must cover local candidates in order")

    def _cache_key(self, request: JudgeRequest) -> str:
        identity = "|".join((content_hash(request), request.review_kind.value, PROVIDER_NAME, LUNA_MODEL, LUNA_EFFORT, request.rubric_version))
        return sha256(identity.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_root / f"{key}.json"

    def _read_cache(self, key: str, request: JudgeRequest) -> JudgeResult | None:
        path = self._cache_path(key)
        try:
            _require_regular_or_absent(path)
            if path.stat().st_mtime < time.time() - CACHE_TTL_SECONDS:
                _delete_cache_file(path)
                return None
            row = json.loads(_read_regular(path))
            result = JudgeResult(**row)
            if (
                result.provider != PROVIDER_NAME or result.model != LUNA_MODEL
                or result.effort != LUNA_EFFORT or result.rubric_version != request.rubric_version
            ):
                return None
            validate_payload(result.payload, output_schema(request))
            self._validate_candidate_indexes(request, result.payload)
            return result
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            _delete_cache_file(path)
            return None

    def _write_cache(self, key: str, result: JudgeResult) -> None:
        _ensure_directory(self._cache_root)
        destination = self._cache_path(key)
        _require_regular_or_absent(destination)
        descriptor, temporary = tempfile.mkstemp(dir=self._cache_root, prefix=f".{key}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({**result.__dict__, "cached": False}, handle, ensure_ascii=True, sort_keys=True)
            os.replace(temporary, destination)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _item_type(item: object) -> str:
    root = getattr(item, "root", item)
    return str(getattr(root, "type", ""))


def _usage_dict(usage: object) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    dumped = getattr(usage, "model_dump", None)
    return dumped(mode="json") if callable(dumped) else {}


def _child_environment(codex_home: Path) -> dict[str, str]:
    """Keep host runtime variables but never pass provider credentials to Codex."""
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("OPENAI_", "ANTHROPIC_"))
    }
    environment["CODEX_HOME"] = str(codex_home)
    return environment


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _ensure_directory(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while True:
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            missing.append(current)
            current = current.parent
            continue
        if stat.S_ISLNK(mode):
            raise LunaProviderFailure(f"unsafe symlink in Luna storage path: {current}")
        if not stat.S_ISDIR(mode):
            raise LunaProviderFailure(f"Luna storage path is not a directory: {current}")
        break
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        mode = directory.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise LunaProviderFailure(f"unsafe symlink in Luna storage path: {directory}")


def _require_regular_or_absent(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise LunaProviderFailure(f"unsafe symlink in Luna storage path: {path}")
    if not stat.S_ISREG(mode):
        raise LunaProviderFailure(f"Luna storage leaf is not a regular file: {path}")


def _is_regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode):
        raise LunaProviderFailure(f"unsafe auth symlink: {path}")
    return stat.S_ISREG(mode)


def _write_regular(path: Path, text: str) -> None:
    _ensure_directory(path.parent)
    directory = _open_directory(path.parent)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, flags, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    finally:
        os.close(directory)


def _read_regular(path: Path) -> str:
    directory = _open_directory(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise LunaProviderFailure("Luna storage leaf is not a regular file")
            return handle.read()
    finally:
        os.close(directory)


def _delete_cache_file(path: Path) -> None:
    try:
        directory = _open_directory(path.parent)
        try:
            descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
            try:
                if stat.S_ISREG(os.fstat(descriptor).st_mode):
                    os.unlink(path.name, dir_fd=directory)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
    except OSError:
        pass


def _open_directory(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            next_descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def _lifecycle_deadline(seconds: float):
    if threading.current_thread() is not threading.main_thread():
        raise LunaProviderFailure("Luna judge timeout requires the main thread")
    previous_handler = signal.getsignal(signal.SIGALRM)
    def timed_out(_signal, _frame):
        raise LunaProviderFailure("Luna judge timed out")
    signal.signal(signal.SIGALRM, timed_out)
    started = time.monotonic()
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.signal(signal.SIGALRM, previous_handler)
        elapsed = time.monotonic() - started
        remaining = max(0.0, previous_timer[0] - elapsed)
        signal.setitimer(signal.ITIMER_REAL, remaining, previous_timer[1])
