"""Provider-neutral contracts and prompts for ADW model review."""
from __future__ import annotations
# pylint: disable=too-many-branches
# The schema validator handles the complete bounded provider wire shape in one pass.

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


RUBRIC_VERSION = "adw-rubric-v1"
COMMENT_RUBRIC = (
    "A comment may state why code is the way it is, but may not describe what code does. "
    "The opening clause decides it. Use describes_code when code is the subject and its behaviour is named; "
    "use states_why when the opening names a decision, constraint, measurement, or consequence."
)
PATTERN_RUBRIC = (
    "Judge only the named pattern. A sentence may be poor for another reason and still be clean for this pattern. "
    "Use the rule, requested fix, and both example sides to decide each candidate."
)
DOCUMENT_RUBRIC = (
    "Coherence: hidden argument order, missing paragraph bridges, unintroduced referents, and contradictions. "
    "Style: repeated paragraph shapes, register shifts, buried subjects, and stock openers or closers. "
    "Quote the sentence you mean exactly."
)


class ReviewKind(StrEnum):
    COMMENT = "comment"
    PATTERN = "pattern"
    DOCUMENT = "document"


@dataclass(frozen=True)
class JudgeRequest:
    review_kind: ReviewKind
    candidates: tuple[str, ...] = ()
    source_context: str = ""
    rule_name: str = ""
    rule_action: str = ""
    violating_examples: tuple[str, ...] = ()
    clean_examples: tuple[str, ...] = ()
    rubric_version: str = RUBRIC_VERSION

    def __post_init__(self) -> None:
        if not self.rubric_version:
            raise ValueError("judge requests need a rubric version")
        if self.review_kind is ReviewKind.DOCUMENT:
            if not self.source_context.strip():
                raise ValueError("document review needs source context")
        elif not self.candidates:
            raise ValueError("candidate review needs candidates")


@dataclass(frozen=True)
class JudgeResult:
    payload: dict[str, Any]
    provider: str
    model: str
    effort: str
    rubric_version: str
    usage: dict[str, Any]
    cached: bool = False


COMMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "verdict", "reason"],
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["describes_code", "states_why"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

PATTERN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "verdict", "reason"],
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["violating", "clean"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notes"],
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["quote", "problem", "fix"],
                "properties": {
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                    "fix": {"type": "string"},
                },
            },
        }
    },
}


def output_schema(request: JudgeRequest) -> dict[str, Any]:
    return {
        ReviewKind.COMMENT: COMMENT_SCHEMA,
        ReviewKind.PATTERN: PATTERN_SCHEMA,
        ReviewKind.DOCUMENT: DOCUMENT_SCHEMA,
    }[request.review_kind]


def build_prompt(request: JudgeRequest) -> str:
    if request.review_kind is ReviewKind.COMMENT:
        items = "\n".join(f"{index}. {text.strip()}" for index, text in enumerate(request.candidates))
        return f"{COMMENT_RUBRIC}\nReturn one item per candidate.\n\nJudge each line.\n{items}"
    if request.review_kind is ReviewKind.PATTERN:
        violating = "\n".join(f"violating: {text}" for text in request.violating_examples)
        clean = "\n".join(f"clean: {text}" for text in request.clean_examples)
        items = "\n".join(f"{index}. {text.strip()}" for index, text in enumerate(request.candidates))
        return (
            f"{PATTERN_RUBRIC}\nPattern: {request.rule_name}\nFix it asks for: {request.rule_action}\n"
            f"Real examples:\n  {violating.replace(chr(10), chr(10) + '  ')}\n"
            f"  {clean.replace(chr(10), chr(10) + '  ')}\n\nJudge each sentence.\n{items}"
        )
    return f"{DOCUMENT_RUBRIC}\n\nDocument:\n{request.source_context}"


def content_hash(request: JudgeRequest) -> str:
    payload = {
        "review_kind": request.review_kind.value,
        "candidates": request.candidates,
        "source_context": request.source_context,
        "rule_name": request.rule_name,
        "rule_action": request.rule_action,
        "violating_examples": request.violating_examples,
        "clean_examples": request.clean_examples,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_payload(payload: object, schema: dict[str, Any]) -> dict[str, Any]:
    _validate(payload, schema)
    assert isinstance(payload, dict)
    return payload


def _validate(value: object, schema: dict[str, Any]) -> None:
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if any(name not in value for name in required):
            raise ValueError("response omitted a required field")
        if schema.get("additionalProperties") is False and any(name not in properties for name in value):
            raise ValueError("response has an unexpected field")
        for name, child_schema in properties.items():
            if name in value:
                _validate(value[name], child_schema)
        return
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError("expected an array")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for item in value:
                _validate(item, item_schema)
        return
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError("expected a string")
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("expected an integer")
    else:
        raise ValueError("unsupported response schema")
    choices = schema.get("enum")
    if choices is not None and value not in choices:
        raise ValueError("response has an unsupported value")
