"""Split out because the Luna request shape has its own contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import claude_luna, claude_native, journal
from lib.judge_contracts import JudgeRequest, JudgeResult


@pytest.fixture(autouse=True)
def _open_data_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opened here, because the gate has its own test file."""
    monkeypatch.setattr(claude_luna, "data_boundary_enabled", lambda _cfg: True)


class Provider:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        return JudgeResult(
            payload={"notes": []}, provider="openai-codex", model="gpt-5.6-luna", effort="high",
            rubric_version=request.rubric_version, usage={"input_tokens": 1},
        )


def _post_payload(path: Path) -> dict:
    return {
        "hook_event_name": "PostToolUse", "session_id": "session", "cwd": str(path.parent),
        "tool_name": "Write", "tool_use_id": "tool-1",
        "tool_input": {"file_path": str(path), "content": "raw host content"},
    }


@pytest.mark.parametrize(("name", "comment"), (
    ("a.ts", "// Counts the retries because the report header needs a total."),
    ("a.sh", "# Counts the retries because the report header needs a total."),
    ("a.go", "// Counts the retries because the report header needs a total."),
))
def test_the_comment_reviewer_reads_every_commentable_language(tmp_path: Path, name: str, comment: str) -> None:
    source = tmp_path / name
    source.write_text(f"{comment}\nvalue = 1\n", encoding="utf-8")

    built = claude_luna.post_request(_post_payload(source))

    assert built is not None
    assert "Counts the retries" in built[1][0].text


def _long_documents(tmp_path: Path) -> Path:
    state_root = tmp_path / "state"
    for name, marker in (("first.md", "FIRST-END"), ("second.md", "SECOND-END")):
        document = tmp_path / name
        document.write_text("A sentence to review.\n" * 900 + marker + "\n", encoding="utf-8")
        journal.record_edit("session", "turn", "tool", document, state_root=state_root)
    return state_root


def test_the_stop_review_splits_long_documents_instead_of_cutting_them(tmp_path: Path) -> None:
    state_root = _long_documents(tmp_path)

    work = claude_luna.stop_request({"session_id": "session", "stop_hook_active": False}, state_root)

    sources = [request.source_context for request, _rows in work]
    assert len(sources) > 1
    assert all(len(source) <= claude_luna.MAX_DOCUMENT_CHARS for source in sources)
    joined = "".join(sources)
    assert "FIRST-END" in joined and "SECOND-END" in joined


def test_a_successful_luna_stop_review_judges_every_request_once(tmp_path: Path) -> None:
    state_root = _long_documents(tmp_path)
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    provider = Provider()
    payload = {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False}

    assert claude_luna.run(payload, provider=provider, state_root=state_root, settings_path=settings, preset_path=preset) == {}
    judged = len(provider.requests)
    assert judged > 1
    claude_luna.run(payload, provider=provider, state_root=state_root, settings_path=settings, preset_path=preset)
    assert len(provider.requests) == judged


def test_the_comment_reviewer_skips_a_file_with_no_comment_syntax(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("# Counts the retries because the report header needs a total.\n", encoding="utf-8")

    assert claude_luna.post_request(_post_payload(source)) is None
