from __future__ import annotations

import json
import os
import operator
import sys
from collections.abc import Callable

try:
    from . import host
except ImportError:
    import host


CONTRACT_MAX_CHARS = 4000
MAX_RESPONSE_BYTES = 4096
MAX_MESSAGE_BYTES = 900
MAX_INPUT_CHARS = 1_000_000
STATE_FAILURE = "Agent discipline state could not be verified. Repair the state store before stopping. Cause: "
UNDECIDABLE_PREFIX = "agent-discipline-watcher could not evaluate this "
UNDECIDABLE_SUFFIX = " and blocked it rather than letting it through. Repair the gate config and retry. Cause: "

_CONTRACT_TEXT = """Agent Discipline Watcher contract. These rules override the agent definition you were given and any style guidance inside it.

Punctuation: no em dash or en dash characters, no double hyphen as a clause break, no spaced hyphen standing in for a dash, no semicolon joining two independent clauses, no apostrophe on a possessive pronoun, no possessive apostrophe on a decade. Use a comma, a period, parentheses, or a plain ASCII hyphen instead.

English: write plain reader-facing prose. Cut filler, throat-clearing, dead metaphor, AI tell phrases, inflated diction, wordiness, empty intensifiers, and buried subjects. State the fact, the evidence, the consequence, and the next action.

Code: intent lives in names, structure, and tests. Delete any comment that narrates what the code does, labels a case by letter or number, apologizes, records change history, or parks deferred work behind a marker. Ship no commented-out code, no speculative one-use abstraction, no skipped or hollow test, no over-long function, no oversized file, and no claim of success without a run.

Stance: be skeptical and direct. Verify changeable facts before claiming them. Challenge weak assumptions and overbuilt solutions. Do not open with praise, agreement, or other empty validators.

Every finding blocks or is reported as an itemized per-line checklist. Treat each row as a separate line to verify, not a summary count. Each row names the file, line, rule, and action. Fix the named file or reply text, then rerun the relevant check. Keep the fix narrow.

Do not end a turn while a finding remains in your own changes. Do not silence a hook, delete hook state, or edit configuration to get past a finding. Do not add a Craftsman suppression marker. Do not broaden the task into style cleanup outside the requested scope."""

CONTRACT = _CONTRACT_TEXT[:CONTRACT_MAX_CHARS]
PARSE_FAILURE = {"_parse_failure": True}


def read_payload() -> dict:
    raw = sys.stdin.read(MAX_INPUT_CHARS + 1)
    if len(raw) > MAX_INPUT_CHARS:
        sys.stderr.write("agent-discipline-watcher: hook payload exceeds the input limit\n")
        return PARSE_FAILURE
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: unreadable hook payload ({exc})\n")
        return PARSE_FAILURE
    if not operator.is_(type(payload), dict):
        sys.stderr.write("agent-discipline-watcher: unreadable hook payload (expected JSON object)\n")
        return PARSE_FAILURE
    return payload


def _clip_utf8(value: object, limit: int) -> str:
    text = str(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[: max(limit - 3, 0)].decode("utf-8", errors="ignore") + "..."


def _safe_text(value: str) -> str:
    """Stripped because a terminal or bidi control in a hook message can rewrite what the reader sees."""
    return "".join(
        character
        if character == "\n" or (
            ord(character) >= 32
            and ord(character) != 127
            and not 0x80 <= ord(character) <= 0x9F
            and not 0x202A <= ord(character) <= 0x202E
            and not 0x2066 <= ord(character) <= 0x2069
        )
        else " "
        for character in value
    )


def _compact_specific(specific: object) -> dict | None:
    if not isinstance(specific, dict):
        return None
    compact: dict[str, object] = {}
    for key, limit in (("hookEventName", 128), ("permissionDecision", 32)):
        value = specific.get(key)
        if isinstance(value, str):
            compact[key] = _clip_utf8(_safe_text(value), limit)
    context = specific.get("additionalContext")
    if isinstance(context, str):
        compact["additionalContext"] = _clip_utf8(_safe_text(context), 900)
    permission_reason = specific.get("permissionDecisionReason")
    if isinstance(permission_reason, str):
        compact["permissionDecisionReason"] = _clip_utf8(_safe_text(permission_reason), 900)
    return compact


def _bounded_payload(payload: dict) -> dict:
    safe_payload = dict(payload)
    for key in ("reason", "systemMessage"):
        value = safe_payload.get(key)
        if isinstance(value, str):
            safe_payload[key] = _safe_text(value)
    specific = safe_payload.get("hookSpecificOutput")
    if isinstance(specific, dict):
        bounded_specific = dict(specific)
        for key in ("hookEventName", "permissionDecision", "additionalContext", "permissionDecisionReason"):
            value = bounded_specific.get(key)
            if isinstance(value, str):
                bounded_specific[key] = _safe_text(value)
        safe_payload["hookSpecificOutput"] = bounded_specific

    raw = json.dumps(safe_payload, ensure_ascii=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= MAX_RESPONSE_BYTES:
        return safe_payload
    reason = _clip_utf8(_safe_text(safe_payload.get("reason", safe_payload.get("systemMessage", ""))), MAX_MESSAGE_BYTES)
    if "decision" in safe_payload:
        compacted = {
            "decision": _clip_utf8(safe_payload["decision"], 64),
            "reason": reason,
        }
    else:
        compacted = {"systemMessage": reason}
        if "reason" in safe_payload:
            compacted["reason"] = _clip_utf8(safe_payload["reason"], MAX_MESSAGE_BYTES)
    compact_specific = _compact_specific(safe_payload.get("hookSpecificOutput"))
    if compact_specific:
        compacted["hookSpecificOutput"] = compact_specific
    return compacted


def write_payload(payload: dict) -> None:
    sys.stdout.write(json.dumps(_bounded_payload(payload), ensure_ascii=True, separators=(",", ":")))
    sys.stdout.write("\n")


def deny(reason: str) -> dict:
    return {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


def claude_pretool_response(payload: dict) -> dict:
    specific = payload.get("hookSpecificOutput")
    if not isinstance(specific, dict) or specific.get("permissionDecision") != "deny":
        return payload
    return {"hookSpecificOutput": dict(specific)}


def claude_feedback_response(payload: dict, event: str) -> dict:
    if payload.get("decision") != "block":
        return payload
    return advise(str(payload.get("reason") or "Fix the blocked findings and retry."), event)


def allow() -> dict:
    return {}


def context(message: str, event: str) -> dict:
    """Use model context because systemMessage is visible only to the user."""
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def stop_block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def system_message(message: str) -> dict:
    return {"systemMessage": message}


def advise(message: str, event: str) -> dict:
    """Put observed findings in model context because a user-only system message cannot make the agent consider them."""
    if host.is_codex_host():
        return context(message, event)
    return {
        "systemMessage": message,
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": message},
    }


def fail_closed(subject: str, fn: Callable[[], dict]) -> dict:
    """Deny naming subject on a raised exception, because a gate that cannot decide must block rather than let the call through."""
    try:
        return fn()
    except Exception as exc:
        return deny(UNDECIDABLE_PREFIX + subject + UNDECIDABLE_SUFFIX + str(exc))
