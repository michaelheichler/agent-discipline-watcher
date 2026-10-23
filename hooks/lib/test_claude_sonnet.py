"""Split from the Luna tests, because this handler makes one batch call through a CLI."""
from __future__ import annotations

import hashlib
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


class Judge:  # pylint: disable=too-few-public-methods
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


def _readme_after_a_two_line_edit(tmp_path: Path, state_root: Path) -> None:
    readme = tmp_path / "README.md"
    sentences = [f"Sentence {number} of the untouched README." for number in range(1, 481)]
    readme.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    journal.record_edit("sonnet", "turn-1", "tool-1", readme, state_root=state_root)
    journal.mark_reviewed("sonnet", journal.read_stop("sonnet", turn_id="turn-1", state_root=state_root), state_root=state_root)
    sentences[99:101] = ["The preset picks the reviewer.", "It also names the model."]
    readme.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    journal.record_edit("sonnet", "turn-2", "tool-2", readme, state_root=state_root)
    session_state.update_state("sonnet", lambda state: {**state, "turn_id": "turn-2"}, state_root)


def test_a_two_line_edit_to_a_long_document_sends_only_those_lines_and_their_context(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _readme_after_a_two_line_edit(tmp_path, state_root)
    judge = Judge(_cli({"items": [], "notes": []}))

    _stop(tmp_path, state_root, judge)

    prompt = judge.prompts[0]
    assert "README.md lines 97-104, changed lines: 100-101" in prompt
    assert "+ The preset picks the reviewer.\n+ It also names the model." in prompt
    assert "Sentence 97 of" in prompt and "Sentence 96 of" not in prompt
    assert "Sentence 480 of" not in prompt
    assert len(prompt) < 2_000


def test_a_reverted_edit_makes_no_model_call(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _readme_after_a_two_line_edit(tmp_path, state_root)
    readme = tmp_path / "README.md"
    readme.write_text("\n".join(f"Sentence {n} of the untouched README." for n in range(1, 481)) + "\n", encoding="utf-8")
    journal.record_edit("sonnet", "turn-2", "tool-3", readme, state_root=state_root)

    assert _stop(tmp_path, state_root, Judge(error=AssertionError("must not judge"))) == {}


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
    _cli({"items": [{"section": 0, "index": 0, "verdict": "maybe", "reason": "x"}], "notes": []}),
))
def test_an_unusable_verdict_says_the_review_did_not_run_and_keeps_the_rows(tmp_path: Path, stdout: str) -> None:
    state_root = _journal(tmp_path, [PATTERN])

    response = _stop(tmp_path, state_root, Judge(stdout))

    assert "decision" not in response
    assert response["systemMessage"].startswith("ADW Sonnet review did not run this turn:")
    assert "stay queued" in response["systemMessage"]
    assert _unreviewed(state_root) == 1


@pytest.mark.parametrize("item", [
    {"section": 0, "index": 1, "verdict": "clean", "reason": "x"},
    {"section": 9, "index": 0, "verdict": "clean", "reason": "x"},
], ids=["missing-candidate", "missing-section"])
def test_a_verdict_item_that_names_no_candidate_leaves_the_candidate_queued(tmp_path: Path, item: dict) -> None:
    state_root = _journal(tmp_path, [PATTERN])

    response = _stop(tmp_path, state_root, Judge(_cli({"items": [item], "notes": []})))

    assert "decision" not in response
    assert _unreviewed(state_root) == 1


UTILIZE = {**PATTERN, "rule": "utilize", "path": "other.md", "text": "We utilize the cache on every request."}
MIXED = {
    "items": [
        {"section": 0, "index": 0, "verdict": "violating", "reason": "Not a pattern."},
        {"section": 1, "index": 0, "verdict": "violating", "reason": "Stock closer."},
    ],
    "notes": [NOTE],
}


def _document_and_two_patterns(tmp_path: Path) -> Path:
    """Sections come out as document 0, ai_closer 1, utilize 2, because documents lead and rules sort by name."""
    policy = {"rule_gates": {"ai_closer": "enforce", "utilize": "enforce"}}
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(policy), encoding="utf-8")
    state_root = tmp_path / "state"
    journal.record_edit("sonnet", "turn-1", "tool", _document(tmp_path), state_root=state_root)
    session_state.update_state(
        "sonnet",
        lambda state: {**state, journal.STATE_KEY: [*state[journal.STATE_KEY], PATTERN, UTILIZE], "turn_id": "turn-1"},
        state_root,
    )
    return state_root


def _next_turn(state_root: Path) -> None:
    session_state.update_state("sonnet", lambda state: {**state, "turn_id": "turn-2"}, state_root)


def test_an_item_naming_the_document_section_voids_only_itself(tmp_path: Path) -> None:
    state_root = _document_and_two_patterns(tmp_path)

    response = _stop(tmp_path, state_root, Judge(_cli(MIXED)))

    _next_turn(state_root)
    queued = [row.get("rule") or row["role"] for row in journal.read_for_stop("sonnet", state_root=state_root)]
    assert response.get("decision") == "block"
    assert CLOSER in response["reason"]
    assert NOTE["problem"] in response["reason"]
    assert queued == ["utilize"]


def test_the_next_stop_resends_only_the_unanswered_pattern(tmp_path: Path) -> None:
    state_root = _document_and_two_patterns(tmp_path)
    _stop(tmp_path, state_root, Judge(_cli(MIXED)))
    _next_turn(state_root)
    retry = Judge(_cli({"items": [], "notes": []}))

    _stop(tmp_path, state_root, retry)

    sent = [(UTILIZE["text"] in prompt, CLOSER in prompt, "A paragraph with enough text" in prompt) for prompt in retry.prompts]
    assert sent == [(True, False, False)]


SAME_FILE = {**PATTERN, "line": 5, "text": "I hope this helps with your project."}


def test_the_next_stop_resends_only_the_skipped_candidate_of_a_file(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [PATTERN, SAME_FILE])
    _stop(tmp_path, state_root, Judge(_cli(VIOLATING)))
    _next_turn(state_root)
    retry = Judge(_cli({"items": [], "notes": []}))

    _stop(tmp_path, state_root, retry)

    assert [(SAME_FILE["text"] in prompt, CLOSER in prompt) for prompt in retry.prompts] == [(True, False)]


def test_a_retry_in_the_same_turn_resends_only_the_skipped_candidate(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [PATTERN, SAME_FILE])
    _stop(tmp_path, state_root, Judge(_cli(VIOLATING)))
    retry = Judge(_cli({"items": [], "notes": []}))

    _stop(tmp_path, state_root, retry)

    assert [(SAME_FILE["text"] in prompt, CLOSER in prompt) for prompt in retry.prompts] == [(True, False)]


def _on_disk(tmp_path: Path, rows: list[dict]) -> list[dict]:
    """Written with a matching hash, because a held row whose file is gone releases its block."""
    lines = {row["line"]: row["text"] for row in rows}
    note = tmp_path / "note.md"
    note.write_text("".join(f"{lines.get(number, 'Plain line.')}\n" for number in range(1, max(lines) + 1)), encoding="utf-8")
    digest = hashlib.sha256(note.read_bytes()).hexdigest()
    return [{**row, "path": str(note), "content_hash": digest} for row in rows]


def test_a_retry_in_the_same_turn_keeps_the_upheld_block(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, _on_disk(tmp_path, [PATTERN, SAME_FILE]))
    _stop(tmp_path, state_root, Judge(_cli(VIOLATING)))

    response = _stop(tmp_path, state_root, Judge(_cli({"items": [], "notes": []})))

    assert response.get("decision") == "block"
    assert CLOSER in response["reason"]


RUN = {**PATTERN, "rule": "choppy_sentences", "path": "run.md", "line": 1, "text": "The hook reads the file. It checks every rule. It writes a report."}
CLOSER_ONLY = {"items": [{"section": 0, "index": 0, "verdict": "violating", "reason": "Stock closer."}], "notes": []}


def _closer_and_run(tmp_path: Path) -> Path:
    """Sections come out as ai_closer 0 and choppy_sentences 1, because rules sort by name."""
    return _journal(tmp_path, [PATTERN, RUN])


def test_a_skipped_parataxis_run_leaves_the_other_verdicts_standing(tmp_path: Path) -> None:
    state_root = _closer_and_run(tmp_path)

    response = _stop(tmp_path, state_root, Judge(_cli(CLOSER_ONLY)))

    _next_turn(state_root)
    queued = [row["rule"] for row in journal.read_for_stop("sonnet", state_root=state_root)]
    assert response.get("decision") == "block"
    assert CLOSER in response["reason"]
    assert queued == ["choppy_sentences"]


def test_the_next_stop_resends_only_the_skipped_parataxis_run(tmp_path: Path) -> None:
    state_root = _closer_and_run(tmp_path)
    _stop(tmp_path, state_root, Judge(_cli(CLOSER_ONLY)))
    _next_turn(state_root)
    retry = Judge(_cli({"items": [], "notes": []}))

    _stop(tmp_path, state_root, retry)

    assert [(RUN["text"] in prompt, CLOSER in prompt) for prompt in retry.prompts] == [(True, False)]


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
        f" 'memory': os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY'), 'cwd': os.getcwd()}}, open({str(log)!r}, 'w'))\n"
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
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert call["memory"] == "1"
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
