"""Locks the single-handler boundary because parallel input mutations race."""
import subprocess
from unittest.mock import patch

import pre_tool


def test_read_only_tool_skips_the_hook_process_output() -> None:
    assert pre_tool.run({"tool_name": "Read"}) == {}


def test_unknown_tool_receives_nonblocking_context() -> None:
    response = pre_tool.run({"tool_name": "FutureWriter"})
    specific = response["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert "additionalContext" in specific
    assert "permissionDecision" not in specific


def test_direct_writer_preserves_a_security_denial() -> None:
    denial = {
        "decision": "block",
        "hookSpecificOutput": {"permissionDecision": "deny"},
    }
    with patch.object(pre_tool.pre_write, "run", return_value=denial):
        assert pre_tool.run({"tool_name": "Write"}) is denial


def test_bash_runs_safety_and_commit_checks_once() -> None:
    with (
        patch.object(pre_tool.pre_bash, "run", return_value={}) as bash,
        patch.object(pre_tool.pre_commit, "run", return_value={}) as commit,
    ):
        response = pre_tool.run({"tool_name": "Bash", "tool_input": {"command": "true"}})
    bash.assert_called_once()
    commit.assert_called_once()
    assert "additionalContext" in response["hookSpecificOutput"]


def test_bash_commit_rewrite_disclosure_survives_dispatch(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    response = pre_tool.run({
        "tool_name": "Bash",
        "tool_input": {"command": 'git commit -m "we ship it; it works"'},
        "cwd": str(tmp_path),
    })

    assert response["systemMessage"]
    assert "rewrote the commit message before the commit ran" in response["systemMessage"]
    assert response["hookSpecificOutput"]["updatedInput"]["command"] == (
        "git commit -m 'we ship it. it works'"
    )
