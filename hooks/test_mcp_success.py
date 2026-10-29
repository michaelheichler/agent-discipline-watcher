from __future__ import annotations

from pathlib import Path

import pytest

import failure
import mcp_success
from lib import session_state

MCP_TOOL = "mcp__serena__find_symbol"


def _config(root: Path) -> dict[str, str]:
    return {"state_root": str(root / "state"), "ledger_root": str(root / "ledger")}


def _call(root: Path, tool: str, **extra: object) -> dict:
    return {"session_id": "m1", "cwd": str(root), "tool_name": tool, "tool_use_id": "t", "tool_input": {}, **extra}


def _fail(root: Path, tool: str, now: float) -> None:
    failure.run(_call(root, tool, error="Cannot extract symbols", tool_use_id=f"f{now}"), _config(root), now=now)


def _server_failures(root: Path, server: str) -> int:
    return session_state.read_state("m1", _config(root)["state_root"])[failure.MCP_HEALTH_KEY][server]["failure_count"]


@pytest.mark.parametrize("tool", [
    pytest.param(MCP_TOOL, id="mcp-tool"),
    pytest.param("Write", id="other-tool"),
])
def test_a_success_never_holds_up_the_turn(tmp_path: Path, tool: str) -> None:
    assert mcp_success.run(_call(tmp_path, tool), _config(tmp_path)) == {}


def test_an_mcp_success_restarts_the_server_backoff_at_one_failure(tmp_path: Path) -> None:
    _fail(tmp_path, MCP_TOOL, 1.0)
    _fail(tmp_path, MCP_TOOL, 2.0)
    mcp_success.run(_call(tmp_path, MCP_TOOL), _config(tmp_path))

    _fail(tmp_path, MCP_TOOL, 3.0)

    assert _server_failures(tmp_path, "serena") == 1


def test_a_success_of_another_server_keeps_the_failing_server_backoff(tmp_path: Path) -> None:
    _fail(tmp_path, MCP_TOOL, 1.0)
    _fail(tmp_path, MCP_TOOL, 2.0)
    mcp_success.run(_call(tmp_path, "mcp__linkup__search"), _config(tmp_path))

    _fail(tmp_path, MCP_TOOL, 3.0)

    assert _server_failures(tmp_path, "serena") == 3
