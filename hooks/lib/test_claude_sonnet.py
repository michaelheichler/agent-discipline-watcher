"""Split from the Luna tests, because this handler makes one batch call through a CLI."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from lib import claude_sonnet, journal, session_state

CLOSER = "Feel free to ask me anything else."
PATTERN = {
    "role": "pattern", "rule": "ai_closer", "path": "note.md", "line": 2, "text": CLOSER,
    "content_hash": "abc", "turn_id": "turn-1",
}
STOP = {"hook_event_name": "Stop", "session_id": "sonnet", "stop_hook_active": False}
VIOLATING = {"items": [{"section": 0, "index": 0, "verdict": "violating", "reason": "Stock closer."}], "notes": []}
CLEAN = {"items": [{"section": 0, "index": 0, "verdict": "clean", "reason": "Fine."}], "notes": []}
NOTE = {"quote": "A paragraph with enough text to inspect.", "problem": "weak bridge", "fix": "Name the transition."}


@pytest.fixture(autouse=True)
def _enforce_the_closer(tmp_path: Path) -> None:
    """Enforced here, because the shipped default only observes this rule."""
    policy = {"rule_gates": {"ai_closer": "enforce"}}
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(policy), encoding="utf-8")


def _cli(structured: object, **extra: object) -> str:
    return json.dumps({"type": "result", "is_error": False, "structured_output": structured, **extra})


class Judge:
    """Kept as a class, because the call count is the contract under test."""

    def __init__(self, stdout: str = "", error: Exception | None = None) -> None:
        self.stdout = stdout
        self.error = error
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.stdout


def _journal(tmp_path: Path, rows: list[dict]) -> Path:
    state_root = tmp_path / "state"
    session_state.write_state("sonnet", {journal.STATE_KEY: rows, "turn_id": "turn-1"}, state_root)
    return state_root


def _document(tmp_path: Path) -> Path:
    document = tmp_path / "doc.md"
    document.write_text("A paragraph with enough text to inspect.\n", encoding="utf-8")
    return document


def _stop(tmp_path: Path, state_root: Path, judge: Judge) -> dict:
    return claude_sonnet.run({**STOP, "cwd": str(tmp_path)}, state_root=state_root, judge=judge)


def _unreviewed(state_root: Path) -> int:
    """Because the current turn is always served, the turn moves on before the read."""
    session_state.update_state("sonnet", lambda state: {**state, "turn_id": "turn-2"}, state_root)
    return len(journal.read_for_stop("sonnet", state_root=state_root))


def test_an_empty_turn_makes_no_model_call(tmp_path: Path) -> None:
    judge = Judge(error=AssertionError("must not judge"))

    assert _stop(tmp_path, tmp_path / "state", judge) == {}
    assert judge.prompts == []


def test_rows_the_project_observes_make_no_call_and_are_marked(tmp_path: Path) -> None:
    (tmp_path / ".agent-discipline.json").write_text(
        json.dumps({"rule_gates": {"ai_closer": "observe"}}), encoding="utf-8",
    )
    state_root = _journal(tmp_path, [PATTERN])
    judge = Judge(error=AssertionError("must not judge"))

    assert _stop(tmp_path, state_root, judge) == {}
    assert _unreviewed(state_root) == 0


def test_the_shipped_observe_default_makes_no_call(tmp_path: Path) -> None:
    (tmp_path / ".agent-discipline.json").write_text("{}", encoding="utf-8")
    judge = Judge(error=AssertionError("must not judge"))

    assert _stop(tmp_path, _journal(tmp_path, [PATTERN]), judge) == {}


def test_a_clean_verdict_passes_and_marks_the_row(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [PATTERN])
    judge = Judge(_cli(CLEAN))

    assert _stop(tmp_path, state_root, judge) == {}
    assert len(judge.prompts) == 1
    assert _unreviewed(state_root) == 0


def test_a_violating_verdict_blocks_with_a_sonnet_titled_finding(tmp_path: Path) -> None:
    response = _stop(tmp_path, _journal(tmp_path, [PATTERN]), Judge(_cli(VIOLATING)))

    assert response["decision"] == "block"
    assert "ADW Sonnet pattern review:" in response["reason"]
    assert 'note.md:2 Wrap-up flourish "Feel free to ask me anything else."' in response["reason"]
    assert "Luna" not in response["reason"]


def test_one_call_answers_a_document_and_a_pattern_by_section(tmp_path: Path) -> None:
    document = _document(tmp_path)
    state_root = tmp_path / "state"
    journal.record_edit("sonnet", "turn-1", "tool", document, state_root=state_root)
    session_state.update_state(
        "sonnet",
        lambda state: {**state, journal.STATE_KEY: [*state[journal.STATE_KEY], PATTERN], "turn_id": "turn-1"},
        state_root,
    )
    judge = Judge(_cli({
        "items": [{"section": 1, "index": 0, "verdict": "violating", "reason": "Stock closer."}], "notes": [NOTE],
    }))

    response = _stop(tmp_path, state_root, judge)

    assert len(judge.prompts) == 1
    assert "Section 0 (document)." in judge.prompts[0] and "Section 1 (pattern)." in judge.prompts[0]
    assert "weak bridge" in response["reason"]
    assert "Wrap-up flourish" in response["reason"]


def test_a_document_note_is_reported(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    journal.record_edit("sonnet", "turn-1", "tool", _document(tmp_path), state_root=state_root)

    response = _stop(tmp_path, state_root, Judge(_cli({"items": [], "notes": [NOTE]})))

    assert response["decision"] == "block"
    assert "weak bridge" in response["reason"]


def test_a_reviewed_document_is_not_sent_again(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    journal.record_edit("sonnet", "turn-1", "tool", _document(tmp_path), state_root=state_root)
    _stop(tmp_path, state_root, Judge(_cli({"items": [], "notes": []})))
    second = Judge(error=AssertionError("must not judge"))

    assert _stop(tmp_path, state_root, second) == {}


@pytest.mark.parametrize("stdout", (
    "not json",
    json.dumps({"is_error": True, "result": "API Error: 404"}),
    json.dumps({"is_error": False}),
    _cli({"items": "nope", "notes": []}),
    _cli({"items": [], "notes": []}),
    _cli({"items": [{"section": 0, "index": 0, "verdict": "maybe", "reason": "x"}], "notes": []}),
    _cli({"items": [{"section": 9, "index": 0, "verdict": "clean", "reason": "x"}], "notes": []}),
))
def test_an_unusable_verdict_says_the_review_did_not_run_and_keeps_the_rows(tmp_path: Path, stdout: str) -> None:
    state_root = _journal(tmp_path, [PATTERN])

    response = _stop(tmp_path, state_root, Judge(stdout))

    assert "decision" not in response
    assert response["systemMessage"].startswith("ADW Sonnet review did not run this turn:")
    assert "stay queued" in response["systemMessage"]
    assert _unreviewed(state_root) == 1


@pytest.mark.parametrize("reason", ("the claude CLI is not on PATH", "the claude CLI timed out after 90 seconds"))
def test_a_judge_failure_is_one_clear_line_and_keeps_the_rows(tmp_path: Path, reason: str) -> None:
    state_root = _journal(tmp_path, [PATTERN])

    response = _stop(tmp_path, state_root, Judge(error=claude_sonnet.ReviewUnavailable(reason)))

    assert response["systemMessage"].count("\n") == 0
    assert reason in response["systemMessage"]
    assert _unreviewed(state_root) == 1


def test_a_failed_review_is_retried_on_the_next_stop(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [PATTERN])
    _stop(tmp_path, state_root, Judge(error=claude_sonnet.ReviewUnavailable("down")))

    response = _stop(tmp_path, state_root, Judge(_cli(VIOLATING)))

    assert response["decision"] == "block"


def test_the_recursion_guard_and_an_active_stop_make_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = _journal(tmp_path, [PATTERN])
    judge = Judge(error=AssertionError("must not judge"))

    assert claude_sonnet.run({**STOP, "stop_hook_active": True}, state_root=state_root, judge=judge) == {}
    assert claude_sonnet.run({**STOP, "hook_event_name": "PostToolUse"}, state_root=state_root, judge=judge) == {}
    monkeypatch.setenv(claude_sonnet.RECURSION_GUARD, "1")
    assert claude_sonnet.run({**STOP, "cwd": str(tmp_path)}, state_root=state_root, judge=judge) == {}


def _fake_claude(tmp_path: Path, stdout: str) -> dict[str, str]:
    """Stands in for the CLI, because a real call costs money and time."""
    bin_dir, log = tmp_path / "bin", tmp_path / "call.json"
    bin_dir.mkdir()
    reply = tmp_path / "reply.json"
    reply.write_text(stdout, encoding="utf-8")
    script = bin_dir / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'guard': os.environ.get('ADW_JUDGE_ACTIVE'),"
        f" 'cwd': os.getcwd()}}, open({str(log)!r}, 'w'))\n"
        f"sys.stdout.write(open({str(reply)!r}).read())\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def test_the_cli_call_has_no_tools_no_hooks_and_no_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _fake_claude(tmp_path, _cli(CLEAN)).items():
        monkeypatch.setenv(key, value)

    claude_sonnet.run({**STOP, "cwd": str(tmp_path)}, state_root=_journal(tmp_path, [PATTERN]))

    call = json.loads((tmp_path / "call.json").read_text(encoding="utf-8"))
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert argv[argv.index("--tools") + 1] == ""
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}
    assert {"-p", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"} <= set(argv)
    assert "--bare" not in argv
    assert json.loads(argv[argv.index("--json-schema") + 1]) == claude_sonnet.BATCH_SCHEMA
    assert "Section 0 (pattern)." in call["stdin"] and CLOSER in call["stdin"]
    assert CLOSER not in " ".join(argv)
    assert call["guard"] == "1"
    assert Path(call["cwd"]).resolve() != tmp_path.resolve()


def test_a_missing_cli_reports_that_the_review_did_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv(claude_sonnet.EXEC_PATH_ENV, raising=False)
    state_root = _journal(tmp_path, [PATTERN])

    response = claude_sonnet.run({**STOP, "cwd": str(tmp_path)}, state_root=state_root)

    assert "claude CLI is not on PATH" in response["systemMessage"]
    assert _unreviewed(state_root) == 1


def test_a_cli_that_exits_with_no_output_reports_the_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _fake_claude(tmp_path, "").items():
        monkeypatch.setenv(key, value)

    response = claude_sonnet.run({**STOP, "cwd": str(tmp_path)}, state_root=_journal(tmp_path, [PATTERN]))

    assert "exited 0 with no output" in response["systemMessage"]


def test_the_launcher_blocks_end_to_end_through_a_fake_cli(tmp_path: Path) -> None:
    env = {**os.environ, **_fake_claude(tmp_path, _cli(VIOLATING)), "HOME": str(tmp_path / "home")}
    env.pop(claude_sonnet.RECURSION_GUARD, None)
    state_root = tmp_path / "home" / ".adw" / "state"
    session_state.write_state("sonnet", {journal.STATE_KEY: [PATTERN], "turn_id": "turn-1"}, state_root)
    launcher = Path(__file__).parents[1] / "claude_sonnet.sh"

    done = subprocess.run(
        [str(launcher)], input=json.dumps({**STOP, "cwd": str(tmp_path)}), env=env,
        capture_output=True, text=True, check=False,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["decision"] == "block"
