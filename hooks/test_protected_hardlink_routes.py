"""Exercise host routes because each writer must honor protected inode ownership."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pre_bash
import pre_mcp
import pre_write


@pytest.mark.parametrize("relative,expected", [
    pytest.param(".adw/state.json", "state_mutation", id="state"),
    pytest.param(".claude/plugins/agent-discipline-watcher/hooks/protected.py",
                 "watcher_install_surface", id="install"),
])
@pytest.mark.parametrize("run,tool,tool_input", [
    pytest.param(pre_write.run, "Write", {"file_path": "alias", "content": "{}"}, id="write"),
    pytest.param(pre_bash.run, "Bash", {"command": "echo x > alias"}, id="bash"),
    pytest.param(pre_mcp.run, "mcp__filesystem__write_file",
                 {"path": "alias", "content": "{}"}, id="mcp"),
])
def test_every_write_route_blocks_an_existing_protected_hard_link(
        tmp_path, monkeypatch, relative, expected, run, tool, tool_input) -> None:
    home = tmp_path / "home"
    target = home / relative
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "alias").hardlink_to(target)
    monkeypatch.setenv("HOME", str(home))
    payload = {"cwd": str(project), "session_id": "hardlink-routes", "tool_name": tool,
               "tool_input": tool_input}
    cfg = {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}

    response = run(payload, cfg)

    assert response.get("decision") == "block"
    rows = (Path(cfg["ledger_root"]) / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert expected in {json.loads(row).get("rule") for row in rows}
