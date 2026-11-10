"""Exercise message inputs because unreadable prose must not skip the commit gate."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import pre_commit
from testing import make_repo, run_git


FILE_OPTIONS = [
    pytest.param("-F message.txt", id="short"),
    pytest.param("--file message.txt", id="long"),
    pytest.param("--file=message.txt", id="long-attached"),
    pytest.param("-Fmessage.txt", id="short-attached"),
    pytest.param("-qFmessage.txt", id="quiet-bundle"),
    pytest.param("-sF message.txt", id="signoff-bundle"),
]


@pytest.fixture
def staged_repo(tmp_path) -> Path:
    repo = make_repo(tmp_path)
    (repo / "note.txt").write_text("Keep the note.\n", encoding="utf-8")
    run_git(repo, "add", "note.txt")
    return repo


def gate(repo, command, root) -> dict:
    payload = {"cwd": str(repo), "session_id": "message-files", "tool_name": "Bash",
               "tool_input": {"command": command}}
    return pre_commit.run(payload, ledger_root=root / "ledger", state_root=root / "state")


def recorded_rules(root) -> set[str]:
    rows = (root / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    return {json.loads(row).get("rule") for row in rows}


@pytest.mark.parametrize("option", FILE_OPTIONS)
def test_file_backed_commit_prose_cannot_skip_scanning(tmp_path, staged_repo, option) -> None:
    (staged_repo / "message.txt").write_text("We ship it; it works.", encoding="utf-8")

    result = gate(staged_repo, f"git commit {option}", tmp_path)

    assert result.get("decision") == "block"
    assert "prose_semicolon" in recorded_rules(tmp_path)


@pytest.mark.parametrize("option", FILE_OPTIONS)
def test_clean_file_backed_commit_prose_stays_released(tmp_path, staged_repo, option) -> None:
    (staged_repo / "message.txt").write_text("Keep the note.", encoding="utf-8")

    result = gate(staged_repo, f"git commit {option}", tmp_path)

    assert result.get("decision") != "block"


@pytest.mark.parametrize("body,blocked", [
    pytest.param("Keep the note.", False, id="clean"),
    pytest.param("We ship it; it works.", True, id="violation"),
])
def test_file_message_resolution_uses_each_git_calls_directory(
        tmp_path, staged_repo, body, blocked) -> None:
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = make_repo(second_root)
    (second / "note.txt").write_text("Keep the note.\n", encoding="utf-8")
    run_git(second, "add", "note.txt")
    (second / "message.txt").write_text(body, encoding="utf-8")
    (staged_repo / "message.txt").write_text("Wrong repository; do not read.", encoding="utf-8")

    result = gate(staged_repo, f"git -C {second} commit -F message.txt", tmp_path)

    assert (result.get("decision") == "block") is blocked


@pytest.mark.parametrize("body,blocked", [
    pytest.param("Keep the note.", False, id="clean"),
    pytest.param("We ship it; it works.", True, id="violation"),
])
def test_literal_stdin_commit_prose_faces_the_message_gate(
        tmp_path, staged_repo, body, blocked) -> None:
    command = f"git commit -F - <<'EOF'\n{body}\nEOF"

    result = gate(staged_repo, command, tmp_path)

    assert (result.get("decision") == "block") is blocked


@pytest.mark.parametrize("option", [
    pytest.param("-F missing.txt", id="missing-file"),
    pytest.param("-F", id="missing-short-operand"),
    pytest.param("--file=", id="empty-long-operand"),
    pytest.param("-F -", id="unavailable-stdin"),
    pytest.param("-F pipe", id="fifo"),
    pytest.param("-F invalid.txt", id="invalid-utf8"),
])
def test_unreadable_commit_message_inputs_fail_closed(tmp_path, staged_repo, option) -> None:
    os.mkfifo(staged_repo / "pipe")
    (staged_repo / "invalid.txt").write_bytes(b"\xff")

    result = gate(staged_repo, f"git commit {option}", tmp_path)

    assert result.get("decision") == "block"
    assert result.get("reason")


def test_persistent_project_policy_locks_do_not_enter_git(tmp_path, staged_repo) -> None:
    ignore = Path(__file__).resolve().parent.parent / ".gitignore"
    (staged_repo / ".gitignore").write_bytes(ignore.read_bytes())
    lock = staged_repo / ".agent-discipline.json.lock"
    lock.touch()

    ignored = run_git(staged_repo, "check-ignore", lock.name)

    assert ignored.strip() == lock.name


def test_repeated_message_options_keep_the_body_in_its_own_paragraph(
        tmp_path, staged_repo) -> None:
    command = 'git commit -m "Keep the note." -m "We ship it; it works."'

    result = gate(staged_repo, command, tmp_path)

    assert result.get("decision") == "block"
    assert "prose_semicolon" in recorded_rules(tmp_path)
    assert ":3 " in result["reason"]


@pytest.mark.parametrize("body, blocked", [
    pytest.param("Keep the note.", False, id="clean"),
    pytest.param("We ship it; it works.", True, id="violation"),
])
def test_tilde_message_inputs_share_the_absolute_home_verdict(tmp_path, staged_repo, monkeypatch, body, blocked) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "message").write_text(body, encoding="utf-8")

    result = gate(staged_repo, "git commit --file=~/message", tmp_path)

    assert (result.get("decision") == "block") is blocked


def test_ambiguous_tilde_message_inputs_fail_closed(tmp_path, staged_repo, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "message").write_text("Keep the note.", encoding="utf-8")
    literal = staged_repo / "~" / "message"
    literal.parent.mkdir()
    literal.write_text("We ship it; it works.", encoding="utf-8")

    result = gate(staged_repo, "git commit --file=~/message", tmp_path)

    assert result.get("decision") == "block"
