"""Centralizes pre-tool control because parallel hook input rewrites race."""
from __future__ import annotations

from lib import payloads
from lib.hookio import context, read_payload, write_payload
import pre_bash
import pre_commit
import pre_mcp
import pre_write

DIRECT_WRITERS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"})
READ_ONLY_TOOLS = frozenset({
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "ToolSearch", "ListAgents",
    "TaskGet", "TaskList", "TaskOutput",
})
WRITE_REMINDER = (
    "Before the next write: keep prose short, preserve concrete WHY comments, "
    "and remove narration comments."
)


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


def _updated_input(response: dict) -> dict | None:
    specific = response.get("hookSpecificOutput")
    if not isinstance(specific, dict):
        return None
    value = specific.get("updatedInput")
    return value if isinstance(value, dict) else None


def _merge(responses: list[dict]) -> dict:
    """Combine here because parallel input mutations have nondeterministic precedence."""
    for response in responses:
        if _is_denial(response):
            return response
    messages = [text for response in responses if (text := _context_text(response))]
    messages.append(WRITE_REMINDER)
    system_messages = [
        text for response in responses if (text := _system_message(response)) != ""
    ]
    updated = next((value for response in responses if (value := _updated_input(response))), None)
    merged = context("\n".join(dict.fromkeys(messages)), "PreToolUse", updated)
    return (
        {**merged, "systemMessage": "\n".join(dict.fromkeys(system_messages))}
        if system_messages
        else merged
    )


def run(payload: dict, config: dict | None = None) -> dict:
    """Route here so one process owns input mutation and permission outcomes."""
    name = payloads.tool_name(payload)
    if name in READ_ONLY_TOOLS:
        return {}
    if name in DIRECT_WRITERS:
        return _merge([pre_write.run(payload, config)])
    if name == "Bash":
        return _merge([pre_bash.run(payload, config), pre_commit.run(payload, config)])
    if name.startswith("mcp__"):
        return _merge([pre_mcp.run(payload, config)])
    return context(WRITE_REMINDER, "PreToolUse") if name else {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
