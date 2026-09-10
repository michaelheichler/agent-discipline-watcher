from __future__ import annotations

from typing import Any

from .judge_contracts import JudgeRequest, JudgeResult, output_schema, validate_payload
from .luna_storage import LunaProviderFailure


def validate_candidate_indexes(request: JudgeRequest, payload: dict[str, Any]) -> None:
    rows = payload.get("items")
    if not isinstance(rows, list):
        return
    if [row["index"] for row in rows] != list(range(len(request.candidates))):
        raise ValueError("response indexes must cover local candidates in order")


def validate_worker_result(
    request: JudgeRequest,
    result: object,
    provider_name: str,
    model_name: str,
    effort_name: str,
) -> JudgeResult:
    try:
        if isinstance(result, JudgeResult):
            result = result.__dict__
        if type(result) is not dict:
            raise ValueError("worker result must be an object")
        expected_fields = {
            "payload", "provider", "model", "effort", "rubric_version", "usage", "cached",
        }
        if set(result) != expected_fields:
            raise ValueError("worker result fields are invalid")
        _validate_identity(result, request, provider_name, model_name, effort_name)
        _validate_types(result)
        payload = validate_payload(result["payload"], output_schema(request))
        validate_candidate_indexes(request, payload)
        return JudgeResult(
            payload=payload,
            provider=result["provider"],
            model=result["model"],
            effort=result["effort"],
            rubric_version=result["rubric_version"],
            usage=result["usage"],
            cached=result["cached"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LunaProviderFailure(
            "Luna worker returned a semantically invalid success result",
            category="worker_protocol",
        ) from exc


def _validate_identity(
    result: dict[str, Any],
    request: JudgeRequest,
    provider_name: str,
    model_name: str,
    effort_name: str,
) -> None:
    expected = {
        "provider": provider_name,
        "model": model_name,
        "effort": effort_name,
        "rubric_version": request.rubric_version,
    }
    for field, value in expected.items():
        if result[field] != value or type(result[field]) is not str:
            raise ValueError(f"worker result {field} identity is invalid")


def _validate_types(result: dict[str, Any]) -> None:
    if type(result["cached"]) is not bool or result["cached"] is not False:
        raise ValueError("worker result cached flag is invalid")
    if type(result["payload"]) is not dict:
        raise ValueError("worker result payload type is invalid")
    if type(result["usage"]) is not dict:
        raise ValueError("worker result usage type is invalid")
