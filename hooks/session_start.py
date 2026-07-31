from __future__ import annotations

from lib.hookio import CONTRACT, read_payload, write_payload

SESSION_START_EVENT = "SessionStart"

PROMPT = (
    "agent-discipline-watcher: keep punctuation ASCII, prefer plain English, "
    "and remove deferred-work comments before writing files."
)


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    """Send the short line to the transcript and the full contract to the model, because systemMessage alone never reaches the model."""
    return {
        "systemMessage": PROMPT,
        "hookSpecificOutput": {
            "hookEventName": SESSION_START_EVENT,
            "additionalContext": CONTRACT,
        },
    }


if __name__ == "__main__":
    write_payload(run(read_payload()))
