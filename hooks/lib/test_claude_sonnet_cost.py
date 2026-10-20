"""Split from the Sonnet tests, because retries, cooldown, and the block bound each spend tokens on their own."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from lib import claude_luna, claude_native, claude_sonnet, journal, reporting, session_state, turn_retry
from lib.document_review import HUNK_NOTICE
from lib.judge_contracts import DOCUMENT_RUBRIC, PATTERN_RUBRIC, JudgeRequest, JudgeResult, ReviewKind

STOP = {"hook_event_name": "Stop", "session_id": "sonnet", "stop_hook_active": False}
NO_SECTION = {"items": [{"section": 9, "index": 0, "verdict": "clean", "reason": "x"}], "notes": []}


def _closer(line: int) -> dict:
    return {
        "role": "pattern", "rule": "ai_closer", "path": "note.md", "line": line,
        "text": f"Feel free to ask me anything else, reader {line}.", "content_hash": "abc", "turn_id": "turn-1",
    }


@pytest.fixture(autouse=True)
def _enforce_the_closer(tmp_path: Path) -> None:
    """Enforced here, because the shipped default only observes this rule."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"rule_gates": {"ai_closer": "enforce"}}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirected, because the Sonnet Stop writes its ledger rows under the home directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


class Judge:  # pylint: disable=too-few-public-methods
    """Kept as a class, because the call count is the contract under test."""

    def __init__(self, structured: object = None, error: Exception | None = None) -> None:
        self.stdout = json.dumps({"type": "result", "is_error": False, "structured_output": structured})
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


def _stop(tmp_path: Path, state_root: Path, judge: Judge) -> dict:
    return claude_sonnet.run({**STOP, "cwd": str(tmp_path)}, state_root=state_root, judge=judge)


def _next_turn(state_root: Path) -> None:
    session_state.update_state("sonnet", lambda state: {**state, "turn_id": "turn-2"}, state_root)


def _unreviewed(state_root: Path) -> int:
    _next_turn(state_root)
    return len(journal.read_for_stop("sonnet", state_root=state_root))


def _verdicts(*answers: tuple[int, str]) -> dict:
    return {"items": [{"section": 0, "index": index, "verdict": verdict, "reason": "r"} for index, verdict in answers], "notes": []}


def _both_channels(response: dict) -> list[str]:
    return [response.get("systemMessage", ""), response.get("hookSpecificOutput", {}).get("additionalContext", "")]


def _dropped_rows() -> list[tuple[str, str]]:
    rows = reporting.read_jsonl(reporting.LEDGER_FILENAME)
    return [(row["rule"], row["path"]) for row in rows if row.get("rule") == "review_dropped"]


def _skipped_twice(tmp_path: Path) -> dict:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, Judge(_verdicts()))
    return _stop(tmp_path, state_root, Judge(_verdicts()))


def _failed_twice(tmp_path: Path) -> tuple[Path, dict]:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, Judge(NO_SECTION))
    return state_root, _stop(tmp_path, state_root, Judge(NO_SECTION))


def _after_cli_failure(tmp_path: Path) -> Path:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, Judge(error=claude_sonnet.CliUnavailable("the claude CLI timed out after 90 seconds")))
    return state_root


def test_a_candidate_the_model_skipped_is_not_reported(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2), _closer(3)])

    response = _stop(tmp_path, state_root, Judge(_verdicts((1, "violating"))))

    assert "reader 3" in response["reason"]
    assert "reader 2" not in response["reason"]


def test_a_candidate_the_model_skipped_is_sent_again_on_the_next_stop(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2), _closer(3)])
    _stop(tmp_path, state_root, Judge(_verdicts((1, "violating"))))
    _next_turn(state_root)
    retry = Judge(_verdicts())

    _stop(tmp_path, state_root, retry)

    assert ["reader 2" in prompt for prompt in retry.prompts] == [True]


def test_a_candidate_skipped_twice_is_named_to_the_user_and_the_agent(tmp_path: Path) -> None:
    response = _skipped_twice(tmp_path)

    assert ["note.md:2" in text for text in _both_channels(response)] == [True, True]


def test_a_candidate_skipped_twice_leaves_a_dropped_review_row_in_the_ledger(tmp_path: Path) -> None:
    _skipped_twice(tmp_path)

    assert _dropped_rows() == [("review_dropped", "note.md")]


def test_a_repeated_candidate_keeps_the_first_answer(tmp_path: Path) -> None:
    response = _stop(tmp_path, _journal(tmp_path, [_closer(2)]), Judge(_verdicts((0, "violating"), (0, "clean"))))

    assert response["decision"] == "block"


def test_a_failed_review_keeps_its_rows_queued(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])

    _stop(tmp_path, state_root, Judge(NO_SECTION))

    assert _unreviewed(state_root) == 1


def test_a_second_failed_review_names_each_dropped_row_to_the_user_and_the_agent(tmp_path: Path) -> None:
    _state_root, response = _failed_twice(tmp_path)

    assert ["note.md:2" in text for text in _both_channels(response)] == [True, True]


def test_a_row_dropped_after_two_failed_reviews_is_not_sent_again(tmp_path: Path) -> None:
    state_root, _response = _failed_twice(tmp_path)

    response = _stop(tmp_path, state_root, Judge(error=AssertionError("must not judge")))

    assert response == {}
    assert _unreviewed(state_root) == 0


def test_a_stop_inside_the_cli_cooldown_says_why_and_until_when_without_running_the_cli(tmp_path: Path) -> None:
    state_root = _after_cli_failure(tmp_path)
    cooling = Judge(error=AssertionError("must not judge"))

    response = _stop(tmp_path, state_root, cooling)

    assert list(response) == ["systemMessage"]
    assert "timed out after 90 seconds" in response["systemMessage"]
    assert re.search(r"\b\d{2}:\d{2}:\d{2}\b", response["systemMessage"])
    assert cooling.prompts == []


def test_the_cli_cooldown_stays_silent_when_nothing_is_queued(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [])
    turn_retry.record_cli_outage("sonnet", "the claude CLI timed out after 90 seconds", state_root)

    assert _stop(tmp_path, state_root, Judge(error=AssertionError("must not judge"))) == {}


def test_the_cli_runs_again_once_the_cooldown_ends(tmp_path: Path) -> None:
    state_root = _after_cli_failure(tmp_path)
    session_state.update_state(
        "sonnet", lambda state: {**state, turn_retry.CLI_OUTAGE_KEY: {"retry_after": time.time() - 1}}, state_root,
    )

    assert _stop(tmp_path, state_root, Judge(_verdicts((0, "violating"))))["decision"] == "block"


def test_a_bad_verdict_does_not_cool_the_cli_down(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2), _closer(3)])
    _stop(tmp_path, state_root, Judge(NO_SECTION))
    retry = Judge(_verdicts())

    _stop(tmp_path, state_root, retry)

    assert len(retry.prompts) == 1


def test_the_rubric_is_stated_once_in_the_system_prompt(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    document.write_text("A paragraph with enough text to inspect.\n", encoding="utf-8")
    state_root = tmp_path / "state"
    journal.record_edit("sonnet", "turn-1", "tool", document, state_root=state_root)
    session_state.update_state(
        "sonnet", lambda state: {**state, journal.STATE_KEY: [*state[journal.STATE_KEY], _closer(2)], "turn_id": "turn-1"},
        state_root,
    )
    judge = Judge(_verdicts())

    _stop(tmp_path, state_root, judge)

    assert "Section 0 (document)." in judge.prompts[0] and "Section 1 (pattern)." in judge.prompts[0]
    assert [rubric in judge.prompts[0] for rubric in (PATTERN_RUBRIC, DOCUMENT_RUBRIC, HUNK_NOTICE)] == [False] * 3
    assert claude_sonnet.SYSTEM_PROMPT.count(PATTERN_RUBRIC) == claude_sonnet.SYSTEM_PROMPT.count(DOCUMENT_RUBRIC) == 1


def _section(title: str, count: int) -> str:
    return "\n".join([f"ADW Sonnet {title} review:", *(f"{n}. {title} row {n} " + "x" * 120 for n in range(1, count + 1))])


def _rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"\d+\. ", line)]


def test_a_short_review_is_shown_whole_and_ends_with_a_report_path() -> None:
    sections = [_section("pattern", 1), _section("document", 1)]

    text = claude_luna.bounded_feedback(sections)
    shown, tail = text.rsplit("\n", 1)

    assert shown == "\n\n".join(sections)
    assert tail.startswith("Full report: ")
    report = tail.removeprefix("Full report: ")
    assert [row["message"] for row in json.loads(Path(report).read_text(encoding="utf-8"))] == sections


def test_a_long_review_lists_five_rows_and_points_at_every_section() -> None:
    sections = [_section("pattern", 4), _section("comment", 4), _section("document", 4)]

    text = claude_luna.bounded_feedback(sections)
    report = text.splitlines()[-1].split(": ", 1)[1]

    assert len(text) <= claude_luna.MAX_FEEDBACK_CHARS
    assert len(_rows(text)) <= 5
    assert text.splitlines()[-1].startswith(f"{12 - len(_rows(text))} more findings: ")
    assert [row["message"] for row in json.loads(Path(report).read_text(encoding="utf-8"))] == sections


class _LunaProvider:  # pylint: disable=too-few-public-methods
    def judge(self, request: JudgeRequest) -> JudgeResult:
        if request.review_kind is ReviewKind.PATTERN:
            payload = {"items": [{"index": n, "verdict": "violating", "reason": "r"} for n in range(len(request.candidates))]}
        else:
            payload = {"notes": [{"quote": "", "problem": f"problem {n} " + "y" * 80, "fix": "f"} for n in range(6)]}
        return JudgeResult(payload, "openai-codex", "gpt-5.6-luna", "high", request.rubric_version, {})


def test_a_luna_stop_keeps_every_section_behind_a_report_path(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    document.write_text("A paragraph with enough text to inspect.\n", encoding="utf-8")
    state_root = tmp_path / "state"
    journal.record_edit("session", "turn-1", "tool", document, state_root=state_root)
    session_state.update_state(
        "session", lambda state: {**state, journal.STATE_KEY: [*state[journal.STATE_KEY], _closer(2), _closer(3)]},
        state_root,
    )
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)

    response = claude_luna.run(
        {**STOP, "session_id": "session", "cwd": str(tmp_path)},
        provider=_LunaProvider(), state_root=state_root, settings_path=settings, preset_path=preset,
    )
    report = response["reason"].splitlines()[-1].split(": ", 1)[1]
    messages = [row["message"] for row in json.loads(Path(report).read_text(encoding="utf-8"))]

    assert len(response["reason"]) <= claude_luna.MAX_FEEDBACK_CHARS
    assert [message.splitlines()[0] for message in messages] == ["ADW Luna document review:", "ADW Luna pattern review:"]
