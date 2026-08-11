from __future__ import annotations

from pathlib import Path

from lib.hookio import CONTRACT, read_payload, write_payload
from lib.reporting import sweep_tool_use_reports

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
    return body if separator else ""


def readable_output_context(path: Path | None = None) -> str:
    skill_path = path or READABLE_OUTPUT_SKILL
    try:
        text = skill_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    body = _strip_frontmatter(text).strip()
    return f"{READABLE_OUTPUT_HEADING}\n\n{body}" if body else ""


def _sweep_reports(payload: dict) -> None:
    transcript_path = str((payload or {}).get("transcript_path") or "")
    if not transcript_path:
        return
    try:
        sweep_tool_use_reports(transcript_path)
    except OSError:
        pass


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    """Send the short line to the transcript and the full contract to the model, because systemMessage alone never reaches the model."""
    _sweep_reports(payload or {})
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
