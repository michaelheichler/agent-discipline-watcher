"""Centralize pre-tool control so one hook owns the permission result."""
from __future__ import annotations

from lib import payloads
from lib.hookio import PARSE_FAILURE, deny, read_payload, write_payload
from lib.payloads import exact_string_dict
import pre_bash
import pre_commit
import pre_mcp
import pre_write

DIRECT_WRITERS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"})
READ_ONLY_TOOLS = frozenset({
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "ToolSearch", "ListAgents",
    "TaskGet", "TaskList", "TaskOutput",
})

UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this tool call and blocked it rather than letting it through. "
    "Repair the hook payload and retry. Cause: "
)


def _invalid_payload(payload: object) -> bool:
    if payload is PARSE_FAILURE or type(payload) is not dict:
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
            return type(value) is not dict or not value
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
    from lib.hookio import context
    merged = context("\n".join(dict.fromkeys(messages)), "PreToolUse") if messages else {}
    return {**merged, "systemMessage": "\n".join(dict.fromkeys(system_messages))} if system_messages else merged


def run(payload: dict, config: dict | None = None) -> dict:
    """Route here so one process owns input mutation and permission outcomes."""
    if _invalid_payload(payload):
        return deny(UNDECIDABLE + "unreadable hook payload")
    name = payloads.tool_name(payload)
    if name in READ_ONLY_TOOLS:
        return {}
    if name in DIRECT_WRITERS:
        return _merge([pre_write.run(payload, config)])
    if name == "Bash":
        return _merge([pre_bash.run(payload, config), pre_commit.run(payload, config)])
    if name.startswith("mcp__"):
        return _merge([pre_mcp.run(payload, config)])
    return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
