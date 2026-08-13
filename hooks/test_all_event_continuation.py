from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MID_TURN_EVENTS = frozenset({
    "PreToolUse",
    "PostToolUse",
    "PostToolBatch",
    "PostToolUseFailure",
    "SubagentStart",
})


def _run(event: str, payload: dict) -> tuple[int, dict]:
    result = subprocess.run(
        [str(ROOT / "run.sh"), event],
        input=json.dumps(payload), text=True, capture_output=True, check=False,
    )
    return result.returncode, json.loads(result.stdout or "{}")


def test_registered_mid_turn_events_never_emit_top_level_blocks(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("# Increment the counter.\nx = 1\n", encoding="utf-8")
    payloads = {
        "UserPromptSubmit": {"prompt": "skip the tests"},
        "PreToolUse": {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": target.read_text()}},
        "PostToolUse": {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
        "PostToolBatch": {"tool_calls": [{"tool_name": "Write", "tool_use_id": "t1", "tool_input": {"file_path": str(target)}}]},
        "PostToolUseFailure": {"tool_name": "Write", "error": "failed"},
        "SubagentStart": {"agent_id": "a1", "agent_type": "test"},
    }
    for event in MID_TURN_EVENTS:
        code, response = _run(event, payloads[event])
        assert code == 0, event
        assert response.get("decision") != "block", (event, response)


def test_only_end_turn_events_may_emit_top_level_blocks() -> None:
    hooks = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert {"Stop", "SubagentStop"} <= set(hooks)
    assert MID_TURN_EVENTS <= set(hooks)


def test_user_prompt_submit_keeps_intentional_blocks(tmp_path: Path) -> None:
    config = tmp_path / ".agent-discipline.json"
    config.write_text(json.dumps({"data_boundary": {"enabled": True}}), encoding="utf-8")
    code, response = _run(
        "UserPromptSubmit",
        {"cwd": str(tmp_path), "prompt": "Review @private.txt"},
    )
    assert code == 0
    assert response["decision"] == "block"
