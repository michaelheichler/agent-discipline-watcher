from __future__ import annotations

import json
import operator
import sys


CONTRACT_MAX_CHARS = 4000
MAX_RESPONSE_BYTES = 4096

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
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except ValueError as exc:
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


def _bounded_payload(payload: dict) -> dict:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= MAX_RESPONSE_BYTES:
        return payload
    reason = _clip_utf8(payload.get("reason", payload.get("systemMessage", "")), 900)
    specific = payload.get("hookSpecificOutput")
    if isinstance(specific, dict):
        compact_specific = {
            key: value
            for key, value in specific.items()
            if key in {"hookEventName", "permissionDecision"}
        }
        context = specific.get("additionalContext")
        if isinstance(context, str):
            compact_specific["additionalContext"] = _clip_utf8(context, 900)
        permission_reason = specific.get("permissionDecisionReason")
        if isinstance(permission_reason, str):
            compact_specific["permissionDecisionReason"] = _clip_utf8(permission_reason, 900)
    else:
        compact_specific = None
    bounded = {"decision": payload["decision"], "reason": reason} if "decision" in payload else {
        "systemMessage": reason,
    }
    if compact_specific:
        bounded["hookSpecificOutput"] = compact_specific
    return bounded


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


def allow() -> dict:
    return {}


def context(message: str, event: str, updated_input: dict | None = None) -> dict:
    """Use model context because systemMessage is visible only to the user."""
    specific: dict[str, object] = {"hookEventName": event, "additionalContext": message}
    if updated_input is not None:
        specific["updatedInput"] = updated_input
    return {"hookSpecificOutput": specific}


def stop_block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def system_message(message: str) -> dict:
    return {"systemMessage": message}


def advise(message: str, event: str) -> dict:
    """Report without stopping the call, so an observed finding must be considered rather than scrolling past."""
    return {
        "systemMessage": message,
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": message},
    }
