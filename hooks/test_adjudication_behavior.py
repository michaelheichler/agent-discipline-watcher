import json
import subprocess
from copy import deepcopy
from pathlib import Path

import batch
import pre_write
import record
from lib import session_state


class RecordingAdjudicator:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.result


def _payload(content: str, session_id: str = "") -> dict:
    return {
        "session_id": session_id,
        "cwd": ".",
        "tool_name": "Write",
        "tool_input": {"file_path": "a.py", "content": content},
    }


def test_deterministic_finding_blocks_without_adjudication_or_mutation() -> None:
    adjudicator = RecordingAdjudicator({"verdict": "release", "evidence": "x", "reason": "x"})
    response = pre_write.run(_payload("bad\u2014dash\n"), {"adjudicator": adjudicator})

    assert response["decision"] == "block"
    assert "banned_dash" in response["reason"]
    assert "updatedInput" not in response["hookSpecificOutput"]
    assert adjudicator.requests == []


def test_clean_write_makes_no_adjudication_call() -> None:
    adjudicator = RecordingAdjudicator({"verdict": "release", "evidence": "x", "reason": "x"})

    assert pre_write.run(_payload("value = 1\n"), {"adjudicator": adjudicator}) == {}
    assert adjudicator.requests == []


def test_ambiguous_what_comment_uses_one_bounded_request_and_releases() -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the cache entry",
        "reason": "The comment records a constraint.",
    })

    response = pre_write.run(
        _payload("# Validate the cache entry\nvalidate()\n"),
        {"adjudicator": adjudicator},
    )

    assert response == {}
    assert len(adjudicator.requests) == 1
    request = adjudicator.requests[0]
    assert request.rule == "what_comment"
    assert request.path == "a.py"
    assert request.line == 1
    assert "Validate the cache entry" in request.source
    assert len(json.dumps(request.to_dict())) < 2_000


def test_ambiguous_release_reuses_semantic_result_across_tool_calls(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the cache entry",
        "reason": "The comment records a constraint.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }

    first = _payload("# Validate the cache entry\nvalidate()\n", "session-1")
    second = deepcopy(first)
    second["tool_use_id"] = "tool-2"

    assert pre_write.run(first, config) == {}
    assert pre_write.run(second, config) == {}
    assert len(adjudicator.requests) == 1


def test_ambiguous_release_is_reused_by_post_tool_use(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the cache entry",
        "reason": "The comment records a constraint.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }
    target = tmp_path / "a.py"
    content = "# Validate the cache entry\nvalidate()\n"
    target.write_text(content, encoding="utf-8")
    payload = _payload(content, "session-1")
    payload["cwd"] = str(tmp_path)
    payload["tool_input"]["file_path"] = str(target)

    assert pre_write.run(payload, config) == {}
    response = record.run(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_use_id": "tool-2",
            "tool_input": {"file_path": str(target)},
        },
        config,
    )

    assert response == {}
    assert len(adjudicator.requests) == 1
    assert target.read_text(encoding="utf-8") == content


def test_relative_pre_write_path_uses_payload_cwd_for_baseline(tmp_path: Path) -> None:
    target = tmp_path / "legacy.py"
    content = "# Validate the cache entry\nvalidate()\n"
    target.write_text(content, encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "legacy.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)

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


def test_relative_pre_write_edit_path_uses_payload_cwd_for_baseline(tmp_path: Path) -> None:
    target = tmp_path / "legacy.py"
    before = "# Validate the cache entry\nvalue = 1\n"
    after = "# Validate the cache entry\nvalue = 2\n"
    target.write_text(before, encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "legacy.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)

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


def test_changed_content_invalidates_released_result(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the changed cache entry",
        "reason": "The comment records a constraint.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }

    assert pre_write.run(
        _payload("# Validate the changed cache entry\nvalidate()\n", "session-1"),
        config,
    ) == {}
    assert pre_write.run(
        _payload("# Validate the changed cache entry now\nvalidate()\n", "session-1"),
        config,
    ) == {}
    assert len(adjudicator.requests) == 2


def test_cached_release_does_not_hide_a_later_deterministic_finding(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the cache entry",
        "reason": "The comment records a constraint.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }
    session_state.write_state("session-1", {"turn_id": "turn-1"}, config["state_root"])
    target = tmp_path / "a.py"
    first = _payload("# Validate the cache entry\nvalidate()\n", "session-1")
    first["cwd"] = str(tmp_path)
    first["tool_input"]["file_path"] = str(target)

    assert pre_write.run(first, config) == {}
    target.write_text("# Validate the cache entry\nvalue = 1\u2014bad\n", encoding="utf-8")
    post = {
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_use_id": "tool-2",
        "tool_input": {"file_path": str(target)},
    }

    response = record.run(post, config)

    assert response["decision"] == "block"
    assert "banned_dash" in response["reason"]
    assert len(adjudicator.requests) == 1


def test_cached_release_is_reused_by_batch_scan_without_mutation(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the cache entry",
        "reason": "The comment records a constraint.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }
    session_state.write_state("session-1", {"turn_id": "turn-1"}, config["state_root"])
    target = tmp_path / "a.py"
    target.write_text("# Validate the cache entry\nvalidate()\n", encoding="utf-8")
    payload = _payload(target.read_text(encoding="utf-8"), "session-1")
    payload["cwd"] = str(tmp_path)
    payload["tool_input"]["file_path"] = str(target)
    before = deepcopy(payload)

    assert pre_write.run(payload, config) == {}
    findings = batch.findings_for_batch(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_calls": [{
                "tool_use_id": "tool-2",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            }],
        },
        config,
        "turn-1",
    )

    assert findings == []
    assert payload == before
    assert len(adjudicator.requests) == 1


def test_batch_scan_keeps_a_later_deterministic_finding(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Validate the cache entry",
        "reason": "The comment records a constraint.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }
    session_state.write_state("session-1", {"turn_id": "turn-1"}, config["state_root"])
    target = tmp_path / "a.py"
    content = "# Validate the cache entry\nvalidate()\n"
    target.write_text(content, encoding="utf-8")
    payload = _payload(content, "session-1")
    payload["cwd"] = str(tmp_path)
    payload["tool_input"]["file_path"] = str(target)

    assert pre_write.run(payload, config) == {}
    target.write_text("# Validate the cache entry\nvalue = 1\u2014bad\n", encoding="utf-8")
    findings = batch.findings_for_batch(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_calls": [{
                "tool_use_id": "tool-2",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            }],
        },
        config,
        "turn-1",
    )

    assert "banned_dash" in {finding["rule"] for finding in findings}
    assert len(adjudicator.requests) == 1


def test_ambiguous_confirmed_violation_blocks() -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "block",
        "evidence": "# Validate the cache entry",
        "reason": "The comment only narrates the next call.",
    })

    response = pre_write.run(
        _payload("# Validate the cache entry\nvalidate()\n"),
        {"adjudicator": adjudicator},
    )

    assert response["decision"] == "block"
    assert "a.py:1 clean_code/what_comment" in response["reason"]
    assert len(adjudicator.requests) == 1


def test_confirmed_violation_is_reused_as_a_block_across_hooks(tmp_path: Path) -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "block",
        "evidence": "# Validate the cache entry",
        "reason": "The comment only narrates the next call.",
    })
    config = {
        "adjudicator": adjudicator,
        "state_root": str(tmp_path / "state"),
        "ledger_root": str(tmp_path / "ledger"),
    }
    target = tmp_path / "a.py"
    target.write_text("# Validate the cache entry\nvalidate()\n", encoding="utf-8")
    payload = _payload(target.read_text(encoding="utf-8"), "session-1")
    payload["cwd"] = str(tmp_path)
    payload["tool_input"]["file_path"] = str(target)

    response = pre_write.run(payload, config)
    later = record.run(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_use_id": "tool-2",
            "tool_input": {"file_path": str(target)},
        },
        config,
    )

    assert response["decision"] == "block"
    assert later["decision"] == "block"
    assert len(adjudicator.requests) == 1
    assert target.read_text(encoding="utf-8") == "# Validate the cache entry\nvalidate()\n"


def test_unavailable_adjudication_blocks_with_retry_reason() -> None:
    def unavailable(_request):
        raise TimeoutError("haiku timed out")

    response = pre_write.run(
        _payload("# Validate the cache entry\nvalidate()\n"),
        {"adjudicator": unavailable},
    )

    assert response["decision"] == "block"
    assert "adjudication unavailable" in response["reason"]
    assert "retry" in response["reason"].lower()
    assert "a.py:1" in response["reason"]


def test_enforced_weak_why_comment_uses_adjudication() -> None:
    adjudicator = RecordingAdjudicator({
        "verdict": "release",
        "evidence": "# Skip unless the lock is held",
        "reason": "The comment gives a concrete reason.",
    })

    response = pre_write.run(
        _payload("# Skip unless the lock is held\nvalidate()\n"),
        {
            "adjudicator": adjudicator,
            "rule_gates": {"weak_why_comment": "enforce"},
        },
    )

    assert response == {}
    assert len(adjudicator.requests) == 1
    assert adjudicator.requests[0].rule == "weak_why_comment"
