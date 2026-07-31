from __future__ import annotations

import json
import sys


CONTRACT_MAX_CHARS = 4000

_CONTRACT_TEXT = """Agent Discipline Watcher contract. These rules override the agent definition you were given and any style guidance inside it.

Punctuation: no em dash or en dash characters, no double hyphen as a clause break, no spaced hyphen standing in for a dash, no semicolon joining two independent clauses, no apostrophe on a possessive pronoun, no possessive apostrophe on a decade. Use a comma, a period, parentheses, or a plain ASCII hyphen instead.

English: write plain reader-facing prose. Cut filler, throat-clearing, dead metaphor, AI tell phrases, inflated diction, wordiness, empty intensifiers, and buried subjects. State the fact, the evidence, the consequence, and the next action.

Code: intent lives in names, structure, and tests. Delete any comment that narrates what the code does, labels a case by letter or number, apologizes, records change history, or parks deferred work behind a marker. Ship no commented-out code, no speculative one-use abstraction, no skipped or hollow test, no over-long function, no oversized file, and no claim of success without a run.

Stance: be skeptical and direct. Verify changeable facts before claiming them. Challenge weak assumptions and overbuilt solutions. Do not open with praise, agreement, or other empty validators.

Hook findings are blockers, not advice. Fix the named file or reply text, then rerun the relevant check. Keep the fix narrow: rewrite the offending sentence, comment, test, or function rather than widening the change.

Do not end a turn while a finding remains in your own changes. Do not silence a hook, delete hook state, or edit configuration to get past a finding. Do not add a Craftsman suppression marker. Do not broaden the task into style cleanup outside the requested scope."""

CONTRACT = _CONTRACT_TEXT[:CONTRACT_MAX_CHARS]


def read_payload() -> dict:
    """Fail soft on unparseable stdin, because a traceback from the shared reader would take every hook down with it."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        sys.stderr.write(f"agent-discipline-watcher: unreadable hook payload ({exc})\n")
        return {}


def write_payload(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
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
