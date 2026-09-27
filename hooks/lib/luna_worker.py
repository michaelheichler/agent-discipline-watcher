"""Separate, because a hung SDK call must die on timeout."""
from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import stat
import sys
from typing import TextIO

from .judge_contracts import JudgeRequest, JudgeResult, ReviewKind
from .luna_provider import (
    CONFIG_OVERRIDES,
    OpenAICodexSdk,
    SdkLaunch,
    run_sdk_request,
)
from .luna_storage import LunaProviderFailure


MAX_ERROR_MESSAGE = 256
DESCRIPTOR_FIELDS = (
    "call_fd", "codex_home_fd", "cwd_fd", "call_identity",
    "codex_home_identity", "cwd_identity",
)
Runner = Callable[[JudgeRequest, SdkLaunch], JudgeResult]


def execute(request: JudgeRequest, launch: SdkLaunch) -> JudgeResult:
    return run_sdk_request(request, launch, OpenAICodexSdk())


def main(*, stdin: TextIO = sys.stdin, run: Runner = execute) -> int:
    try:
        request, launch = _decode_request(json.loads(stdin.read()))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _write_error("request", "invalid Luna worker request")
        return 2
    try:
        _prepare_descriptor_launch(launch)
        result = run(request, launch)
        print(json.dumps({"ok": True, "result": result.__dict__}, ensure_ascii=True))
        return 0
    except LunaProviderFailure as exc:
        _write_error(exc.category, _bounded_message(str(exc), "Luna provider failed"))
        return 1
    except BaseException as exc:
        category, message = _classify_sdk_error(exc)
        _write_error(category, message)
        return 70


def _decode_request(row: object) -> tuple[JudgeRequest, SdkLaunch]:
    if not isinstance(row, dict):
        raise TypeError("worker request must be an object")
    config_overrides = tuple(row["config_overrides"])
    if config_overrides != CONFIG_OVERRIDES:
        raise ValueError("worker config overrides do not match the provider contract")
    launch = _decode_launch(row, config_overrides)
    return _decode_judge_request(row), launch


def _decode_launch(row: dict, config_overrides: tuple[str, ...]) -> SdkLaunch:
    if any(field in row for field in DESCRIPTOR_FIELDS):
        return _decode_descriptor_launch(row, config_overrides)
    return _decode_path_launch(row, config_overrides)


def _decode_descriptor_launch(row: dict, config_overrides: tuple[str, ...]) -> SdkLaunch:
    if not all(field in row for field in DESCRIPTOR_FIELDS):
        raise ValueError("worker runtime descriptors are incomplete")
    return SdkLaunch(
        codex_home=Path("../home"), cwd=Path("."), config_overrides=config_overrides,
        call_fd=_decode_fd(row["call_fd"]),
        codex_home_fd=_decode_fd(row["codex_home_fd"]),
        cwd_fd=_decode_fd(row["cwd_fd"]),
        call_identity=_decode_identity(row["call_identity"]),
        codex_home_identity=_decode_identity(row["codex_home_identity"]),
        cwd_identity=_decode_identity(row["cwd_identity"]),
    )


def _decode_path_launch(row: dict, config_overrides: tuple[str, ...]) -> SdkLaunch:
    codex_home = Path(row["codex_home"])
    cwd = Path(row["cwd"])
    if not codex_home.is_absolute() or not cwd.is_absolute():
        raise ValueError("worker runtime paths must be absolute")
    return SdkLaunch(codex_home=codex_home, cwd=cwd, config_overrides=config_overrides)


def _decode_judge_request(row: dict) -> JudgeRequest:
    return JudgeRequest(
        review_kind=ReviewKind(row["review_kind"]),
        candidates=tuple(row["candidates"]),
        source_context=row["source_context"],
        rule_name=row["rule_name"],
        rule_action=row["rule_action"],
        violating_examples=tuple(row["violating_examples"]),
        clean_examples=tuple(row["clean_examples"]),
        rubric_version=row["rubric_version"],
    )


def _decode_fd(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 3:
        raise ValueError("worker runtime descriptor is invalid")
    return value


def _decode_identity(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple)) or len(value) != 2
        or any(isinstance(part, bool) or not isinstance(part, int) for part in value)
    ):
        raise ValueError("worker runtime descriptor identity is invalid")
    return int(value[0]), int(value[1])


def _prepare_descriptor_launch(launch: SdkLaunch) -> None:
    if launch.cwd_fd is None:
        return
    _require(
        launch.call_fd is not None and launch.codex_home_fd is not None
        and launch.cwd_identity is not None and launch.call_identity is not None
        and launch.codex_home_identity is not None,
        "Luna worker runtime descriptors are incomplete",
    )
    _verify_directory_descriptor(launch.call_fd, launch.call_identity, "call")
    _verify_directory_descriptor(launch.cwd_fd, launch.cwd_identity, "cwd")
    _verify_directory_descriptor(launch.codex_home_fd, launch.codex_home_identity, "home")
    current, parent, relative_cwd, relative_home = _enter_confined_cwd(launch)
    _require(_identity(current) == launch.cwd_identity, "Luna worker cwd descriptor changed")
    _require(
        _identity(parent) == launch.call_identity,
        "Luna worker cwd is no longer under the runtime descriptor",
    )
    _require(
        _is_directory_at(relative_cwd, launch.cwd_identity),
        "Luna worker cwd path is no longer confined",
    )
    _require(
        _is_directory_at(relative_home, launch.codex_home_identity),
        "Luna worker home path is no longer confined",
    )


def _enter_confined_cwd(launch: SdkLaunch) -> tuple[os.stat_result, ...]:
    try:
        os.fchdir(launch.cwd_fd)
        return (
            os.stat(".", follow_symlinks=False),
            os.stat("..", follow_symlinks=False),
            os.stat("cwd", dir_fd=launch.call_fd, follow_symlinks=False),
            os.stat("home", dir_fd=launch.call_fd, follow_symlinks=False),
        )
    except OSError as exc:
        raise LunaProviderFailure(
            "Luna worker runtime paths are no longer confined", category="configuration",
        ) from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LunaProviderFailure(message, category="configuration")


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _is_directory_at(metadata: os.stat_result, identity: tuple[int, int] | None) -> bool:
    return stat.S_ISDIR(metadata.st_mode) and _identity(metadata) == identity


def _verify_directory_descriptor(
    descriptor: int, expected: tuple[int, int], label: str,
) -> None:
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise LunaProviderFailure(
            f"Luna worker {label} descriptor is unavailable", category="configuration",
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise LunaProviderFailure(
            f"Luna worker {label} descriptor is not a directory", category="configuration",
        )
    if (metadata.st_dev, metadata.st_ino) != expected:
        raise LunaProviderFailure(
            f"Luna worker {label} descriptor changed", category="configuration",
        )


def _classify_sdk_error(exc: BaseException) -> tuple[str, str]:
    names = {kind.__name__ for kind in type(exc).__mro__}
    if names & {"ServerBusyError", "RetryLimitExceededError"}:
        return "overload", "Luna remained overloaded after three attempts"
    if names & {"TransportClosedError", "TimeoutError", "ConnectionError", "BrokenPipeError", "EOFError"}:
        return "transport", "Luna SDK transport failed"
    if names & {
        "CodexError", "JsonRpcError", "CodexRpcError", "ParseError",
        "InvalidRequestError", "MethodNotFoundError", "InvalidParamsError", "InternalRpcError",
    }:
        return "sdk", "Luna SDK request failed"
    if isinstance(exc, FileNotFoundError):
        return "configuration", "The pinned Codex runtime is unavailable; reinstall ADW runtime dependencies"
    return "internal", "Luna worker failed internally"


def _bounded_message(message: str, fallback: str) -> str:
    collapsed = " ".join(message.split())
    return (collapsed or fallback)[:MAX_ERROR_MESSAGE]


def _write_error(category: str, message: str) -> None:
    print(json.dumps({
        "ok": False,
        "error": {"category": category[:64], "message": _bounded_message(message, "Luna worker failed")},
    }, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
