"""ADW-owned process boundary for the official openai-codex SDK."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

from .judge_contracts import JudgeRequest, ReviewKind
from .luna_provider import (
    CONFIG_OVERRIDES,
    OpenAICodexSdk,
    SdkLaunch,
    run_sdk_request,
)
from .luna_storage import LunaProviderFailure


MAX_ERROR_MESSAGE = 256


def execute(request: JudgeRequest, launch: SdkLaunch):
    return run_sdk_request(request, launch, OpenAICodexSdk())


def main() -> int:
    try:
        request, launch = _decode_request(json.loads(sys.stdin.read()))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _write_error("request", "invalid Luna worker request")
        return 2
    try:
        _prepare_descriptor_launch(launch)
        result = execute(request, launch)
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
    descriptor_fields = (
        "call_fd", "codex_home_fd", "cwd_fd", "call_identity",
        "codex_home_identity", "cwd_identity",
    )
    has_descriptors = any(field in row for field in descriptor_fields)
    if has_descriptors:
        if not all(field in row for field in descriptor_fields):
            raise ValueError("worker runtime descriptors are incomplete")
        call_fd = _decode_fd(row["call_fd"])
        codex_home_fd = _decode_fd(row["codex_home_fd"])
        cwd_fd = _decode_fd(row["cwd_fd"])
        call_identity = _decode_identity(row["call_identity"])
        codex_home_identity = _decode_identity(row["codex_home_identity"])
        cwd_identity = _decode_identity(row["cwd_identity"])
        codex_home = Path("../home")
        cwd = Path(".")
    else:
        codex_home = Path(row["codex_home"])
        cwd = Path(row["cwd"])
        if not codex_home.is_absolute() or not cwd.is_absolute():
            raise ValueError("worker runtime paths must be absolute")
        call_fd = codex_home_fd = cwd_fd = None
        call_identity = codex_home_identity = cwd_identity = None
    request = JudgeRequest(
        review_kind=ReviewKind(row["review_kind"]),
        candidates=tuple(row["candidates"]),
        source_context=row["source_context"],
        rule_name=row["rule_name"],
        rule_action=row["rule_action"],
        violating_examples=tuple(row["violating_examples"]),
        clean_examples=tuple(row["clean_examples"]),
        rubric_version=row["rubric_version"],
    )
    launch = SdkLaunch(
        codex_home=codex_home, cwd=cwd, config_overrides=config_overrides,
        call_fd=call_fd, call_identity=call_identity,
        codex_home_fd=codex_home_fd, cwd_fd=cwd_fd,
        codex_home_identity=codex_home_identity, cwd_identity=cwd_identity,
    )
    return request, launch


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
    if (
        launch.call_fd is None or launch.codex_home_fd is None or launch.cwd_identity is None
        or launch.call_identity is None or launch.codex_home_identity is None
    ):
        raise LunaProviderFailure(
            "Luna worker runtime descriptors are incomplete", category="configuration",
        )
    _verify_directory_descriptor(launch.call_fd, launch.call_identity, "call")
    _verify_directory_descriptor(launch.cwd_fd, launch.cwd_identity, "cwd")
    _verify_directory_descriptor(launch.codex_home_fd, launch.codex_home_identity, "home")
    try:
        os.fchdir(launch.cwd_fd)
        current = os.stat(".", follow_symlinks=False)
        parent = os.stat("..", follow_symlinks=False)
        relative_cwd = os.stat("cwd", dir_fd=launch.call_fd, follow_symlinks=False)
        relative_home = os.stat("home", dir_fd=launch.call_fd, follow_symlinks=False)
    except OSError as exc:
        raise LunaProviderFailure(
            "Luna worker runtime paths are no longer confined", category="configuration",
        ) from exc
    if (current.st_dev, current.st_ino) != launch.cwd_identity:
        raise LunaProviderFailure(
            "Luna worker cwd descriptor changed", category="configuration",
        )
    if (parent.st_dev, parent.st_ino) != launch.call_identity:
        raise LunaProviderFailure(
            "Luna worker cwd is no longer under the runtime descriptor", category="configuration",
        )
    if (
        not stat.S_ISDIR(relative_cwd.st_mode)
        or (relative_cwd.st_dev, relative_cwd.st_ino) != launch.cwd_identity
    ):
        raise LunaProviderFailure(
            "Luna worker cwd path is no longer confined", category="configuration",
        )
    if (
        not stat.S_ISDIR(relative_home.st_mode)
        or (relative_home.st_dev, relative_home.st_ino) != launch.codex_home_identity
    ):
        raise LunaProviderFailure(
            "Luna worker home path is no longer confined", category="configuration",
        )


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
