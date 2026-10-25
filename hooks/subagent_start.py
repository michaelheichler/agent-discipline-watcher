"""SubagentStart injection, because neither SessionStart nor UserPromptSubmit fires inside a subagent, so a spawned agent would otherwise write blind into gates it was never shown."""
from __future__ import annotations

from lib import agent_types
from lib.hookio import CONTRACT, context, read_payload, write_payload

SUBAGENT_START_EVENT = "SubagentStart"


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    """Because a subagent must never start without its rules, a failed type record still sends the contract."""
    settings = config if isinstance(config, dict) else {}
    try:
        agent_types.remember(payload, settings.get("state_root"))
    except (OSError, RuntimeError, ValueError):
        pass
    return context(CONTRACT, SUBAGENT_START_EVENT)


if __name__ == "__main__":
    write_payload(run(read_payload()))
