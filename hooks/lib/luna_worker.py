"""ADW-owned process boundary for the official openai-codex SDK."""
from __future__ import annotations

import json
from pathlib import Path
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
    codex_home = Path(row["codex_home"])
    cwd = Path(row["cwd"])
    if not codex_home.is_absolute() or not cwd.is_absolute():
        raise ValueError("worker runtime paths must be absolute")
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
    )
    return request, launch


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
