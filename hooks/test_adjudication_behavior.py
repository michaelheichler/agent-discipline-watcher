from __future__ import annotations

from pathlib import Path

import pre_write
import record
from testing import init_repo, run_git as _git


def _payload(content: str, session_id: str = "") -> dict:
    return {
        "session_id": session_id,
        "cwd": ".",
        "tool_name": "Write",
        "tool_input": {"file_path": "a.py", "content": content},
    }


def test_deterministic_finding_blocks_without_mutation() -> None:
    payload = _payload("bad\u2014dash\n")
    response = pre_write.run(payload, {})

    assert response["decision"] == "block"
    assert "banned_dash" in response["reason"]
    assert "updatedInput" not in response["hookSpecificOutput"]


def test_clean_write_passes_without_mutation() -> None:
    payload = _payload("value = 1\n")

    assert pre_write.run(payload, {}) == {}
    assert payload["tool_input"]["content"] == "value = 1\n"


def test_what_comment_blocks_without_external_adjudication() -> None:
    calls: list[object] = []

    def release(request: object) -> dict[str, str]:
        calls.append(request)
        return {"verdict": "release", "evidence": "x", "reason": "release"}

    response = pre_write.run(
        _payload("# Validate the cache entry\nvalidate()\n"),
        {"adjudicator": release},
    )

    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]
    assert calls == []


def _committed_file(root: Path, content: str) -> Path:
    target = root / "legacy.py"
    target.write_text(content, encoding="utf-8")
    init_repo(root)
    _git(root, "add", "legacy.py")
    _git(root, "commit", "-q", "-m", "seed")
    return target


def test_relative_write_path_uses_payload_cwd_for_baseline(tmp_path: Path) -> None:
    content = "# Validate the cache entry\nvalidate()\n"
    _committed_file(tmp_path, content)

    response = pre_write.run(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_input": {"file_path": "legacy.py", "content": content},
        },
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
    )

    assert "decision" not in response
    assert "already carried 1 findings you did not write" in response["systemMessage"]


def test_relative_edit_path_uses_payload_cwd_for_baseline(tmp_path: Path) -> None:
    before = "# Validate the cache entry\nvalue = 1\n"
    after = "# Validate the cache entry\nvalue = 2\n"
    _committed_file(tmp_path, before)

    response = pre_write.run(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "legacy.py",
                "old_string": before,
                "new_string": after,
            },
        },
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
    )

    assert "decision" not in response


def test_post_write_blocks_strict_findings_without_mutating_file(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    content = "# Validate the cache entry\nvalidate()\n"
    target.write_text(content, encoding="utf-8")

    response = record.run(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_use_id": "tool-2",
            "tool_input": {"file_path": str(target)},
        },
        {"baseline": "none"},
    )

    assert response["decision"] == "block"
    assert "what_comment" in response["reason"]
    assert target.read_text(encoding="utf-8") == content
