"""Because a success proves the MCP server healthy, it must clear the failure count that pre_mcp backs off on."""
from __future__ import annotations

from failure import record_success
from lib import payloads
from lib.hookio import PARSE_FAILURE, read_payload, write_payload

MCP_PREFIX = "mcp__"


def run(payload: dict, config: dict | None = None) -> dict:
    if payload is PARSE_FAILURE or not payloads.tool_name(payload).startswith(MCP_PREFIX):
        return {}
    record_success(payload, config)
    return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
