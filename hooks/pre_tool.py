"""Keep pre-tool dispatch in one hook because separate permission results can conflict and weaken enforcement."""
from __future__ import annotations

import operator

from lib import payloads
from lib.hookio import PARSE_FAILURE, claude_pretool_response, context, deny, read_payload, write_payload
from lib.payloads import exact_string_dict
import pre_bash
import pre_commit
import pre_mcp
import pre_write

DIRECT_WRITERS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"})

UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this tool call and blocked it rather than letting it through. "
    "Repair the hook payload and retry. Cause: "
)


def _invalid_payload(payload: object) -> bool:
    if payload is PARSE_FAILURE or not operator.is_(type(payload), dict):
        return True
    name = payloads.tool_name(payload)
    if not name:
        return True
    if name not in DIRECT_WRITERS and name != "Bash":
        return False
    fields = exact_string_dict(payload)
    for key in ("tool_input", "toolInput", "input"):
        if key in fields:
            value = fields[key]
            return not operator.is_(type(value), dict) or not value
    return True


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


def _dispatch(payload: dict, config: dict | None) -> dict:
    if _invalid_payload(payload):
        return deny(UNDECIDABLE + "unreadable hook payload")
    name = payloads.tool_name(payload)
    if name in DIRECT_WRITERS:
        return pre_write.run(payload, config)
    if name == "Bash":
        return _merge([pre_bash.run(payload, config), pre_commit.run(payload, config)])
    if name.startswith("mcp__"):
        return pre_mcp.run(payload, config)
    return {}


def run(payload: dict, config: dict | None = None) -> dict:
    """Route here so that one process owns input mutation and permission outcomes, blocking rather than passing the call through when the dispatcher itself cannot decide."""
    try:
        return _dispatch(payload, config)
    except Exception as exc:
        return deny(UNDECIDABLE + str(exc))


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
