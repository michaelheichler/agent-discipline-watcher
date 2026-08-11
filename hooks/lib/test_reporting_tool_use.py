"""Locks the tool-use report contract because the Haiku reviewer trusts path derivation, mode, and expiry."""
import json
import os
import stat
import time
from pathlib import Path

import embeddings
import reporting

HELPER_OK = """#!/usr/bin/env python3
import json, sys
data = json.load(sys.stdin.buffer)
texts = data["texts"]
sys.stdout.write(json.dumps({"embeddings": [[float(len(t)), 1.0] for t in texts]}))
"""


def setup_function(_function) -> None:
    embeddings.clear_cache()
    os.environ.pop(embeddings.ENV_VAR, None)


def _transcript(tmp_path) -> str:
    path = tmp_path / "project" / "session-1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return str(path)


def test_report_path_is_unique_per_tool_use_id(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    first = reporting.tool_use_report_path(transcript, "session-1", "tool-a")
    second = reporting.tool_use_report_path(transcript, "session-1", "tool-b")
    assert first != second
    assert first.parent == second.parent
    assert first.parent.name == reporting.TOOL_USE_REPORT_DIRNAME


def test_write_creates_a_bounded_0600_report_in_a_0700_directory(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    written = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="t1",
        target_path="/tmp/example.py", tool_name="Write",
        cleanup_counts={"dashes": 2}, unresolved=[],
    )
    path = Path(written)
    assert path.is_file()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    assert path.stat().st_size <= reporting.TOOL_USE_REPORT_MAX_BYTES


def test_report_reflects_effective_cleanup_counts_and_target(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    written = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="t1",
        target_path="/tmp/example.py", tool_name="Edit",
        cleanup_counts={"dashes": 3, "comments": 1},
        unresolved=[{"path": "/tmp/example.py", "line": 4, "rule": "weak_why_comment", "snippet": "because it helps"}],
    )
    body = json.loads(Path(written).read_text(encoding="utf-8"))
    assert body["target_path"] == "/tmp/example.py"
    assert body["tool_name"] == "Edit"
    assert body["cleanup_counts"] == {"dashes": 3, "comments": 1}
    assert body["unresolved"][0]["rule"] == "weak_why_comment"
    assert "protocol_version" in body and "prototype_version" in body


def test_size_cap_drops_matches_and_trims_unresolved(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(reporting, "TOOL_USE_REPORT_MAX_BYTES", 500)
    transcript = _transcript(tmp_path)
    unresolved = [
        {"path": "/tmp/example.py", "line": n, "rule": "weak_why_comment", "snippet": "x" * 200}
        for n in range(10)
    ]
    written = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="t1",
        target_path="/tmp/example.py", tool_name="Write",
        cleanup_counts={}, unresolved=unresolved,
    )
    body = json.loads(Path(written).read_text(encoding="utf-8"))
    assert len(body["unresolved"]) <= 3


def test_parallel_tool_use_ids_do_not_collide(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    first = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="tool-a",
        target_path="/tmp/a.py", tool_name="Write", cleanup_counts={}, unresolved=[],
    )
    second = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="tool-b",
        target_path="/tmp/b.py", tool_name="Write", cleanup_counts={}, unresolved=[],
    )
    assert first != second
    assert json.loads(Path(first).read_text())["target_path"] == "/tmp/a.py"
    assert json.loads(Path(second).read_text())["target_path"] == "/tmp/b.py"


def test_sweep_removes_only_expired_reports(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    fresh = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="fresh",
        target_path="/tmp/a.py", tool_name="Write", cleanup_counts={}, unresolved=[],
    )
    stale = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="stale",
        target_path="/tmp/b.py", tool_name="Write", cleanup_counts={}, unresolved=[],
    )
    old_time = time.time() - 10_000
    os.utime(stale, (old_time, old_time))
    removed = reporting.sweep_tool_use_reports(transcript, max_age_seconds=3600)
    assert removed == 1
    assert Path(fresh).is_file()
    assert not Path(stale).is_file()


def test_missing_transcript_path_returns_none(tmp_path) -> None:
    assert reporting.write_tool_use_report(
        transcript_path="", session_id="s1", tool_use_id="t1",
        target_path="/tmp/a.py", tool_name="Write", cleanup_counts={}, unresolved=[],
    ) is None


def test_ambiguous_comment_enriches_with_nearest_embedding_example(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text(HELPER_OK, encoding="utf-8")
    helper.chmod(helper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(embeddings.ENV_VAR, str(helper))
    transcript = _transcript(tmp_path)
    written = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="t1",
        target_path="/tmp/a.py", tool_name="Write", cleanup_counts={},
        unresolved=[{"path": "/tmp/a.py", "line": 1, "rule": "what_comment", "snippet": "loads the cache"}],
    )
    body = json.loads(Path(written).read_text(encoding="utf-8"))
    assert "embedding_matches" in body
    match = next(iter(body["embedding_matches"].values()))
    assert "similarity" in match and "label" in match


def test_without_helper_env_no_embedding_matches_key(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    written = reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="t1",
        target_path="/tmp/a.py", tool_name="Write", cleanup_counts={},
        unresolved=[{"path": "/tmp/a.py", "line": 1, "rule": "what_comment", "snippet": "loads the cache"}],
    )
    body = json.loads(Path(written).read_text(encoding="utf-8"))
    assert "embedding_matches" not in body


def test_read_tool_use_report_round_trips(tmp_path) -> None:
    transcript = _transcript(tmp_path)
    reporting.write_tool_use_report(
        transcript_path=transcript, session_id="s1", tool_use_id="t1",
        target_path="/tmp/a.py", tool_name="Write", cleanup_counts={"dashes": 1}, unresolved=[],
    )
    body = reporting.read_tool_use_report(transcript, "s1", "t1")
    assert body["cleanup_counts"] == {"dashes": 1}
    assert reporting.read_tool_use_report(transcript, "s1", "missing") is None
