"""Split out because the Luna request shape has its own contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import claude_luna, claude_native, journal, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult


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
    payload = {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False, "cwd": str(tmp_path)}

    assert claude_luna.run(payload, provider=provider, state_root=state_root, settings_path=settings, preset_path=preset) == {}
    judged = len(provider.requests)
    assert judged > 1
    claude_luna.run(payload, provider=provider, state_root=state_root, settings_path=settings, preset_path=preset)
    assert len(provider.requests) == judged


def _readme_after_a_two_line_edit(tmp_path: Path, state_root: Path) -> None:
    readme = tmp_path / "README.md"
    sentences = [f"Sentence {number} of the untouched README." for number in range(1, 481)]
    readme.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    journal.record_edit("session", "turn-1", "tool-1", readme, state_root=state_root)
    journal.mark_reviewed("session", journal.read_stop("session", turn_id="turn-1", state_root=state_root), state_root=state_root)
    sentences[99:101] = ["The preset picks the reviewer.", "It also names the model."]
    readme.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    journal.record_edit("session", "turn-2", "tool-2", readme, state_root=state_root)
    session_state.update_state("session", lambda state: {**state, "turn_id": "turn-2"}, state_root)


def test_a_two_line_edit_to_a_long_document_sends_only_those_lines_and_their_context(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _readme_after_a_two_line_edit(tmp_path, state_root)

    work = claude_luna.stop_request({"session_id": "session", "stop_hook_active": False}, state_root)

    ((request, _rows),) = work
    assert "README.md lines 97-104, changed lines: 100-101" in request.source_context
    assert "+ The preset picks the reviewer.\n+ It also names the model." in request.source_context
    assert "Sentence 97 of" in request.source_context and "Sentence 96 of" not in request.source_context
    assert "Sentence 480 of" not in request.source_context
    assert len(request.source_context) < 1_500


def test_a_reverted_edit_makes_no_luna_call(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _readme_after_a_two_line_edit(tmp_path, state_root)
    readme = tmp_path / "README.md"
    readme.write_text("\n".join(f"Sentence {n} of the untouched README." for n in range(1, 481)) + "\n", encoding="utf-8")
    journal.record_edit("session", "turn-2", "tool-3", readme, state_root=state_root)
    provider = Provider()
    payload = {"hook_event_name": "Stop", "session_id": "session", "stop_hook_active": False, "cwd": str(tmp_path)}

    response = claude_luna.run(payload, provider=provider, state_root=state_root, **_luna_paths(tmp_path))

    assert response == {} and provider.requests == []


def _luna_paths(tmp_path: Path) -> dict:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    return {"settings_path": settings, "preset_path": preset}


def test_the_comment_reviewer_skips_a_file_with_no_comment_syntax(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("# Counts the retries because the report header needs a total.\n", encoding="utf-8")

    assert claude_luna.post_request(_post_payload(source)) is None
