from __future__ import annotations

import json
from typing import Any

from .judge_contracts import JudgeRequest
from .luna_storage import LunaProviderFailure


def request_payload(request: JudgeRequest, launch: object) -> dict[str, Any]:
    return {
        "review_kind": request.review_kind.value,
        "candidates": request.candidates,
        "source_context": request.source_context,
        "rule_name": request.rule_name,
        "rule_action": request.rule_action,
        "violating_examples": request.violating_examples,
        "clean_examples": request.clean_examples,
        "rubric_version": request.rubric_version,
        "call_fd": launch.call_fd,
        "codex_home_fd": launch.codex_home_fd,
        "cwd_fd": launch.cwd_fd,
        "call_identity": launch.call_identity,
        "codex_home_identity": launch.codex_home_identity,
        "cwd_identity": launch.cwd_identity,
        "config_overrides": launch.config_overrides,
    }


def response_result(returncode: int | None, stdout: str) -> dict[str, Any]:
    row = json.loads(stdout)
    if not isinstance(row, dict):
        raise ValueError("worker response must be an object")
    if returncode != 0 or row.get("ok") is not True:
        error = row.get("error")
        if not isinstance(error, dict):
            raise ValueError("worker response omitted a typed error")
        category = error.get("category")
        message = error.get("message")
        if not isinstance(category, str) or not category or len(category) > 64:
            raise ValueError("worker error category is invalid")
        if not isinstance(message, str) or not message or len(message) > 256:
            raise ValueError("worker error message is invalid")
        raise LunaProviderFailure(message, category=category)
    result = row.get("result")
    if not isinstance(result, dict):
        raise ValueError("worker response omitted a result")
    return result
