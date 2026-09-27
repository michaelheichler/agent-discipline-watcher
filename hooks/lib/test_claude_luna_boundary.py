"""Split out because the other Luna tests open the boundary."""
from __future__ import annotations

import json
from pathlib import Path

from lib import claude_luna, claude_native, journal
from lib.judge_contracts import JudgeRequest


class Provider:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> None:
        self.requests.append(request)
        raise AssertionError("a closed data boundary must not reach the model")


def test_a_closed_boundary_keeps_the_claude_luna_stop_review_local(tmp_path: Path) -> None:
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"data_boundary": {"enabled": False}}), encoding="utf-8")
    document = tmp_path / "doc.md"
    document.write_text("A paragraph that would leave the machine.\n", encoding="utf-8")
    journal.record_edit("session", "turn-1", "tool", document, state_root=tmp_path / "state")
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    provider = Provider()
    payload = {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False, "cwd": str(tmp_path)}

    response = claude_luna.run(payload, provider=provider, state_root=tmp_path / "state", settings_path=settings, preset_path=preset)

    assert response == {}
    assert provider.requests == []
