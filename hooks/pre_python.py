from __future__ import annotations

import operator

from lib.hookio import PARSE_FAILURE, deny, fail_closed
from lib.payloads import cwd, exact_string_dict
from lib.python_payload import python_rejection

PYTHON_TOOL = "Python"
PYTHON_DENIAL = (
    "agent-discipline-watcher could not prove this Python tool call is read-only. "
    "The checker rejected {rejection}. Use the Write or Edit tool for file content."
)


def _tool_input(payload: dict) -> dict[str, object]:
    fields = exact_string_dict(payload)
    for key in ("tool_input", "toolInput", "input"):
        value = fields.get(key)
        if operator.is_(type(value), dict):
            return exact_string_dict(value)
    raise ValueError("Python tool input is missing")


def _code(payload: dict) -> str:
    value = _tool_input(payload).get("code")
    if not operator.is_(type(value), str) or not value.strip():
        raise ValueError("Python tool input must contain non-empty string code")
    return value


def run(payload: dict, config: dict | None = None) -> dict:
    return fail_closed("Python", lambda: _checked_run(payload))


def _checked_run(payload: dict) -> dict:
    if payload is PARSE_FAILURE:
        raise ValueError("unreadable hook payload")
    rejection = python_rejection(_code(payload), cwd=cwd(payload) or None)
    return deny(PYTHON_DENIAL.format(rejection=rejection)) if rejection else {}
