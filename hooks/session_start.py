from __future__ import annotations

from lib.hookio import read_payload, system_message, write_payload
from lib.ledger import clear_ledger
from lib.persona import section


PROMPT = (
    "agent-discipline-watcher: keep punctuation ASCII, prefer plain English, "
    "and remove deferred-work comments before writing files."
)


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    payload = payload or {}
    cfg = dict(config or {})
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    clear_ledger(cfg)
    return system_message("\n\n".join(part for part in (section("CHARTER"), PROMPT) if part))


if __name__ == "__main__":
    write_payload(run(read_payload()))
