"""Keep pre-tool dispatch in one hook because separate permission results can conflict and weaken enforcement."""
from __future__ import annotations

import operator
from collections.abc import Callable
from typing import NamedTuple

from lib import payloads
from lib.hookio import (
    PARSE_FAILURE, UNREADABLE_PAYLOAD, claude_pretool_response, config_failure, context, deny, payload_failure,
    read_payload, write_payload,
)
from lib.payloads import exact_string_dict
import pre_bash
import pre_commit
import pre_mcp
import pre_python
import pre_write

DIRECT_WRITERS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"})
PYTHON_TOOLS = frozenset({"Python"})



def _invalid_payload(payload: object) -> bool:
    if payload is PARSE_FAILURE or not operator.is_(type(payload), dict):
        return True
    name = payloads.tool_name(payload)
    if not name:
        return True
    if name not in DIRECT_WRITERS and name not in PYTHON_TOOLS and name != "Bash":
        return False
    tool_input = _first_tool_input(exact_string_dict(payload))
    if not operator.is_(type(tool_input), dict) or not tool_input:
        return True
    return name == "Bash" and not operator.is_(type(tool_input.get("command")), str)


def _first_tool_input(fields: dict) -> object:
    for key in ("tool_input", "toolInput", "input"):
        if key in fields:
            return fields[key]
    return None


def _is_denial(response: dict) -> bool:
    specific = response.get("hookSpecificOutput")
    return response.get("decision") == "block" or (
        isinstance(specific, dict) and specific.get("permissionDecision") == "deny"
    )


def _context_text(response: dict) -> str:
    specific = response.get("hookSpecificOutput")
    if isinstance(specific, dict):
        value = specific.get("additionalContext")
        if isinstance(value, str):
            return value
    value = response.get("systemMessage")
    return value if isinstance(value, str) else ""


def _system_message(response: dict) -> str:
    value = response.get("systemMessage")
    return value if isinstance(value, str) else ""


def _merge(responses: list[dict]) -> dict:
    for response in responses:
        if _is_denial(response):
            return response
    messages = [text for response in responses if (text := _context_text(response))]
    system_messages = [
        text for response in responses if (text := _system_message(response)) != ""
    ]
    if not messages and not system_messages:
        return {}
    merged = context("\n".join(dict.fromkeys(messages)), "PreToolUse") if messages else {}
    return {**merged, "systemMessage": "\n".join(dict.fromkeys(system_messages))} if system_messages else merged


Gate = Callable[[dict, "dict | None"], dict]


class Gates(NamedTuple):
    write: Gate = pre_write.run
    bash: Gate = pre_bash.run
    commit: Gate = pre_commit.run
    python: Gate = pre_python.run
    mcp: Gate = pre_mcp.run


def _dispatch(payload: dict, config: dict | None, gates: Gates) -> dict:
    if _invalid_payload(payload):
        return deny(payload_failure(UNREADABLE_PAYLOAD))
    name = payloads.tool_name(payload)
    if name in DIRECT_WRITERS:
        return gates.write(payload, config)
    if name == "Bash":
        return _merge([gates.bash(payload, config), gates.commit(payload, config)])
    if name in PYTHON_TOOLS:
        return gates.python(payload, config)
    if name.startswith("mcp__"):
        return gates.mcp(payload, config)
    return {}


def run(payload: dict, config: dict | None = None, *, gates: Gates = Gates()) -> dict:
    """Route here so that one process owns input mutation and permission outcomes, blocking rather than passing the call through when the dispatcher itself cannot decide."""
    try:
        return _dispatch(payload, config, gates)
    except Exception as exc:
        return deny(config_failure("tool call", exc))


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
