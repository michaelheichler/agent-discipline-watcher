"""SubagentStart injection, because neither SessionStart nor UserPromptSubmit fires inside a subagent, so a spawned agent would otherwise write blind into gates it was never shown."""
from __future__ import annotations

from lib.hookio import CONTRACT, context, read_payload, write_payload

SUBAGENT_START_EVENT = "SubagentStart"


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    return context(CONTRACT, SUBAGENT_START_EVENT)


if __name__ == "__main__":
    write_payload(run(read_payload()))
