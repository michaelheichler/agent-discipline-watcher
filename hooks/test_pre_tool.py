"""Locks the single-handler boundary because parallel input mutations race."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pre_tool
from lib.hookio import PARSE_FAILURE


def test_read_only_tool_skips_the_hook_process_output() -> None:
    assert pre_tool.run({"tool_name": "Read"}) == {}


def test_malformed_payload_blocks_before_tool_routing() -> None:
    response = pre_tool.run(PARSE_FAILURE)

    assert response["decision"] == "block"
    assert "unreadable hook payload" in response["reason"]


def test_non_object_stdin_is_rejected_by_the_pretool_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("pre_tool.py"))],
        input=json.dumps([]), text=True, capture_output=True, check=False,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["decision"] == "block"


def test_payload_without_tool_name_is_rejected() -> None:
    response = pre_tool.run({})

    assert response["decision"] == "block"


def test_known_writer_with_malformed_tool_input_is_rejected() -> None:
    response = pre_tool.run({"tool_name": "Write", "tool_input": "bad-shape"})

    assert response["decision"] == "block"


def test_unknown_tool_receives_no_unconditional_reminder() -> None:
    assert pre_tool.run({"tool_name": "FutureWriter"}) == {}


def test_direct_writer_preserves_a_security_denial() -> None:
    denial = {
        "decision": "block",
        "hookSpecificOutput": {"permissionDecision": "deny"},
    }
    with patch.object(pre_tool.pre_write, "run", return_value=denial):
        assert pre_tool.run({"tool_name": "Write", "tool_input": {"content": "x"}}) is denial


def test_bash_runs_safety_and_commit_checks_once() -> None:
    with (
        patch.object(pre_tool.pre_bash, "run", return_value={}) as bash,
        patch.object(pre_tool.pre_commit, "run", return_value={}) as commit,
    ):
        response = pre_tool.run({"tool_name": "Bash", "tool_input": {"command": "true"}})
    bash.assert_called_once()
    commit.assert_called_once()
    assert response == {}


def test_bash_commit_message_violation_blocks_without_rewriting(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    response = pre_tool.run({
        "tool_name": "Bash",
        "tool_input": {"command": 'git commit -m "we ship it; it works"'},
        "cwd": str(tmp_path),
    })

    assert response["decision"] == "block"
    assert "commit_message.md:1 punctuation/prose_semicolon" in response["reason"]
    assert "updatedInput" not in response["hookSpecificOutput"]
