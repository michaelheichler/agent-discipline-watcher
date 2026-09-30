from __future__ import annotations

import re
from typing import Any

from .judge_contracts import JudgeRequest, JudgeResult, output_schema, validate_payload
from .luna_storage import LunaProviderFailure


LUNA_MODEL_PATTERN = re.compile(r"^gpt-(\d+(?:\.\d+)*)-luna$")


def parse_luna_version(identifier: str) -> "tuple[int, ...] | None":
    """Shared, not duplicated, since two copies would drift apart."""
    match = LUNA_MODEL_PATTERN.match(identifier)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def validate_candidate_indexes(request: JudgeRequest, payload: dict[str, Any]) -> None:
    rows = payload.get("items")
    if not isinstance(rows, list):
        return
    if [row["index"] for row in rows] != list(range(len(request.candidates))):
        raise ValueError("response indexes must cover local candidates in order")


def validate_worker_result(request: JudgeRequest, result: object, provider_name: str, effort_name: str) -> JudgeResult:
    """Nothing here is trusted, since the worker runs unsupervised."""
    try:
        row = _coerced_result(result)
        _validate_identity(row, request, provider_name, effort_name)
        _validate_types(row)
        payload = validate_payload(row["payload"], output_schema(request))
        validate_candidate_indexes(request, payload)
        return JudgeResult(
            payload=payload, provider=row["provider"], model=row["model"], effort=row["effort"],
            rubric_version=row["rubric_version"], usage=row["usage"], cached=row["cached"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LunaProviderFailure(
            "Luna worker returned a semantically invalid success result",
            category="worker_protocol",
        ) from exc


def _coerced_result(result: object) -> dict[str, Any]:
    """Fixed set, since a stray key could hide bad data."""
    if isinstance(result, JudgeResult):
        result = result.__dict__
    if type(result) is not dict:
        raise ValueError("worker result must be an object")
    expected_fields = {"payload", "provider", "model", "effort", "rubric_version", "usage", "cached"}
    if set(result) != expected_fields:
        raise ValueError("worker result fields are invalid")
    return result


def _validate_identity(result: dict[str, Any], request: JudgeRequest, provider_name: str, effort_name: str) -> None:
    """Checked by shape, since resolving ended the pinned constant."""
    expected = {"provider": provider_name, "effort": effort_name, "rubric_version": request.rubric_version}
    for field, value in expected.items():
        if result[field] != value or type(result[field]) is not str:
            raise ValueError(f"worker result {field} identity is invalid")
    model = result["model"]
    if type(model) is not str or parse_luna_version(model) is None:
        raise ValueError("worker result model identity is invalid")


def _validate_types(result: dict[str, Any]) -> None:
    if type(result["cached"]) is not bool or result["cached"] is not False:
        raise ValueError("worker result cached flag is invalid")
    if type(result["payload"]) is not dict:
        raise ValueError("worker result payload type is invalid")
    if type(result["usage"]) is not dict:
        raise ValueError("worker result usage type is invalid")
