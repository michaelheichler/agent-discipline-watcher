from __future__ import annotations

from lib.hookio import read_payload, system_message, write_payload


PROMPT = (
    "agent-discipline-watcher: keep punctuation ASCII, prefer plain English, "
    "and remove deferred-work comments before writing files."
)


def run(payload: dict | None = None, config: dict | None = None) -> dict:
    return system_message(PROMPT)


if __name__ == "__main__":
    write_payload(run(read_payload()))
