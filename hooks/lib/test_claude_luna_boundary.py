"""Split out because the other Luna tests never set a data boundary."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import claude_luna, claude_native, journal, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind

COMMENT = "# Counts the retries because the report header needs a total.\nvalue = 1\n"
NO_NOTES = {"notes": []}


class Provider:  # pylint: disable=too-few-public-methods
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        return JudgeResult(self.payload, "openai-codex", "gpt-5.6-luna", "high", request.rubric_version, {})


def _config(tmp_path: Path, config: dict | None) -> None:
    if config is not None:
        (tmp_path / ".agent-discipline.json").write_text(json.dumps(config), encoding="utf-8")


def _preset(tmp_path: Path) -> dict:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    return {"settings_path": settings, "preset_path": preset}


@pytest.mark.parametrize("config", (None, {"data_boundary": {"enabled": False}}))
def test_choosing_the_luna_preset_is_the_consent_to_review_the_stop_rows(tmp_path: Path, config: dict | None) -> None:
    _config(tmp_path, config)
    document = tmp_path / "doc.md"
    document.write_text("A paragraph that goes to the reviewer.\n", encoding="utf-8")
    journal.record_edit("session", "turn-1", "tool", document, state_root=tmp_path / "state")
    provider = Provider(NO_NOTES)
    payload = {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False, "cwd": str(tmp_path)}

    response = claude_luna.run(payload, provider=provider, state_root=tmp_path / "state", **_preset(tmp_path))

    assert response == {}
    assert [request.review_kind for request in provider.requests] == [ReviewKind.DOCUMENT]
    assert "A paragraph that goes to the reviewer." in provider.requests[0].source_context


def test_the_post_tool_review_runs_without_a_boundary_and_marks_no_journal_row(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text(COMMENT, encoding="utf-8")
    state_root = tmp_path / "state"
    journal.record_edit("session", "turn-1", "tool", source, state_root=state_root)
    provider = Provider({"items": [{"index": 0, "verdict": "describes_code", "reason": "Names behavior."}]})
    payload = {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(tmp_path),
        "tool_name": "Write", "tool_use_id": "tool-1", "tool_input": {"file_path": str(source)},
    }

    response = claude_luna.run(payload, provider=provider, state_root=state_root, **_preset(tmp_path))

    assert [request.review_kind for request in provider.requests] == [ReviewKind.COMMENT]
    assert "Names behavior." in response["hookSpecificOutput"]["additionalContext"]
    assert journal.REVIEWED_KEY not in session_state.read_state("session", state_root)
