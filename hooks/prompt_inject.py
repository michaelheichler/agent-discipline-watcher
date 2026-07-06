from __future__ import annotations

from lib.correction import is_correction
from lib.hookio import read_payload, write_payload
from lib.persona import section


def run(payload: dict | None = None) -> dict:
    payload = payload or {}
    prompt = payload.get("prompt") if isinstance(payload.get("prompt"), str) else ""
    parts = [section("REFLEX")]
    if is_correction(prompt):
        parts.append(section("NUDGE"))
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n\n".join(part for part in parts if part),
        }
    }


if __name__ == "__main__":
    write_payload(run(read_payload()))
