from __future__ import annotations

import sys
from pathlib import Path

from lib import retention, session_state
from lib.hookio import CONTRACT, read_payload, write_payload

SESSION_START_EVENT = "SessionStart"
READABLE_OUTPUT_HEADING = "READABLE OUTPUT RULES ACTIVE (main agent only)"
READABLE_OUTPUT_SKILL = (
    Path(__file__).resolve().parents[1] / "skills" / "readable-output" / "SKILL.md"
)

PROMPT = (
    "agent-discipline-watcher: keep punctuation ASCII, prefer plain English, "
    "and remove deferred-work comments before writing files."
)


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    _frontmatter, separator, body = text[4:].partition("\n---\n")
    return body if separator else text


def readable_output_context(path: Path | None = None) -> str:
    skill_path = path or READABLE_OUTPUT_SKILL
    try:
        text = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"agent-discipline-watcher: readable-output skill unreadable: {exc}\n")
        return ""
    body = _strip_frontmatter(text).strip()
    return f"{READABLE_OUTPUT_HEADING}\n\n{body}" if body else ""


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    """Send the short line to the transcript and the full contract to the model, because systemMessage alone never reaches the model."""
    fields = payload if isinstance(payload, dict) else {}
    session_id = fields.get("session_id")
    if isinstance(session_id, str) and session_id:
        settings = config if isinstance(config, dict) else {}
        state_root = settings.get("state_root") if isinstance(settings.get("state_root"), str) else None
        ledger_root = settings.get("ledger_root") if isinstance(settings.get("ledger_root"), str) else None
        session_state.acquire_session_lease(session_id, state_root)
        retention.sweep(state_root=state_root, ledger_root=ledger_root)
    readable = readable_output_context()
    context = f"{CONTRACT}\n\n{readable}" if readable else CONTRACT
    return {
        "systemMessage": PROMPT,
        "hookSpecificOutput": {
            "hookEventName": SESSION_START_EVENT,
            "additionalContext": context,
        },
    }


if __name__ == "__main__":
    write_payload(run(read_payload()))
