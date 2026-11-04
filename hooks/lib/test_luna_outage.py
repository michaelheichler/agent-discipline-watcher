"""Split from the Luna handler tests, because an outage must keep findings queued without trapping the agent at Stop."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from lib import claude_luna, claude_native, journal, luna_outage, reporting, session_state, turn_retry
from lib.judge_contracts import JudgeRequest, JudgeResult
from lib.luna_storage import LunaProviderFailure

SESSION = "outage"
DOWN = "subscription unavailable"
STOP = {"hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": False}
VIOLATING = {"items": [{"index": 0, "verdict": "violating", "reason": "Stock closer."}]}


def _closer(line: int, path: str = "note.md") -> dict:
    return {
        "role": "pattern", "rule": "ai_closer", "path": path, "line": line,
        "text": f"Feel free to ask me anything else, reader {line}.", "content_hash": "abc", "turn_id": "turn-1",
    }


@pytest.fixture(autouse=True)
def _enforce_the_closer(tmp_path: Path) -> None:
    """Enforced here, because the shipped default only observes this rule."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"rule_gates": {"ai_closer": "enforce"}}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirected, because a Luna Stop writes its ledger rows under the home directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


class Provider:  # pylint: disable=too-few-public-methods
    """Kept as a class, because the call count is the contract under test."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return JudgeResult(VIOLATING, "openai-codex", "gpt-5.6-luna", "high", request.rubric_version, {})


def _down(reason: str = DOWN) -> Provider:
    return Provider(LunaProviderFailure(reason, category="authentication"))


def _failing(category: str) -> Provider:
    return Provider(LunaProviderFailure(DOWN, category=category))


def _journal(tmp_path: Path, rows: list[dict]) -> Path:
    state_root = tmp_path / "state"
    session_state.write_state(SESSION, {journal.STATE_KEY: rows, "turn_id": "turn-1"}, state_root)
    return state_root


def _luna_paths(tmp_path: Path) -> dict:
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    return {"settings_path": settings, "preset_path": preset}


def _stop(tmp_path: Path, state_root: Path, provider: Provider) -> dict:
    return claude_luna.run({**STOP, "cwd": str(tmp_path)}, provider=provider, state_root=state_root, **_luna_paths(tmp_path))


def _cooldown_over(state_root: Path) -> None:
    """Rewound in the state file, because the cooldown takes no clock."""
    session_state.update_state(
        SESSION, lambda state: {**state, turn_retry.CLI_OUTAGE_KEY: {"retry_after": time.time() - 1}}, state_root,
    )


def _queued_lines(state_root: Path) -> list[int]:
    """Because the current turn is always served, the turn moves on before the read."""
    session_state.update_state(SESSION, lambda state: {**state, "turn_id": "turn-2"}, state_root)
    return [row["line"] for row in journal.read_for_stop(SESSION, state_root=state_root)]


def _failed_twice(tmp_path: Path, rows: list[dict]) -> tuple[Path, dict]:
    state_root = _journal(tmp_path, rows)
    _stop(tmp_path, state_root, _down())
    _cooldown_over(state_root)
    return state_root, _stop(tmp_path, state_root, _down())


def _both_channels(response: dict) -> list[str]:
    return [response.get("systemMessage", ""), response.get("hookSpecificOutput", {}).get("additionalContext", "")]


def _dropped_paths() -> list[str]:
    rows = reporting.read_jsonl(reporting.LEDGER_FILENAME)
    return [row["path"] for row in rows if row.get("rule") == luna_outage.DROPPED_RULE]


def _post_payload(source: Path) -> dict:
    return {
        "hook_event_name": "PostToolUse", "session_id": SESSION, "cwd": str(source.parent),
        "tool_name": "Write", "tool_use_id": "tool-1", "tool_input": {"file_path": str(source)},
    }


def _commented_source(tmp_path: Path) -> Path:
    source = tmp_path / "a.py"
    source.write_text("# Counts the retries because the report header needs a total.\nvalue = 1\n", encoding="utf-8")
    return source


@pytest.mark.parametrize("reason", [
    pytest.param(DOWN, id="one-line"),
    pytest.param("first line\nsecond line", id="multi-line"),
])
def test_a_failed_review_reports_one_line_without_blocking_the_stop(tmp_path: Path, reason: str) -> None:
    response = _stop(tmp_path, _journal(tmp_path, [_closer(2)]), _down(reason))

    assert "decision" not in response
    assert response["systemMessage"].count("\n") == 0
    assert reason.split("\n", maxsplit=1)[0] in response["systemMessage"]


def test_a_failed_review_keeps_its_rows_queued(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])

    _stop(tmp_path, state_root, _down())

    assert _queued_lines(state_root) == [2]


def test_a_stop_inside_the_cooldown_says_why_and_until_when_without_calling_luna(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, _down())
    cooling = Provider(AssertionError("must not judge"))

    response = _stop(tmp_path, state_root, cooling)

    assert list(response) == ["systemMessage"]
    assert DOWN in response["systemMessage"]
    assert re.search(r"\b\d{2}:\d{2}:\d{2}\b", response["systemMessage"])
    assert cooling.requests == []


def test_a_stop_inside_the_cooldown_keeps_the_rows_queued(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, _down())

    _stop(tmp_path, state_root, Provider(AssertionError("must not judge")))

    assert _queued_lines(state_root) == [2]


def test_the_cooldown_stays_silent_when_nothing_is_queued(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [])
    turn_retry.record_cli_outage(SESSION, DOWN, state_root)

    assert _stop(tmp_path, state_root, Provider(AssertionError("must not judge"))) == {}


def test_luna_reviews_again_once_the_cooldown_ends(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, _down())
    _cooldown_over(state_root)

    assert _stop(tmp_path, state_root, Provider())["decision"] == "block"


def test_a_second_failed_review_names_the_dropped_row_to_the_user_and_the_agent(tmp_path: Path) -> None:
    _state_root, response = _failed_twice(tmp_path, [_closer(2)])

    assert ["note.md:2" in text for text in _both_channels(response)] == [True, True]


def test_a_second_failed_review_still_does_not_block(tmp_path: Path) -> None:
    _state_root, response = _failed_twice(tmp_path, [_closer(2)])

    assert "decision" not in response


def test_a_first_failed_review_writes_no_dropped_row(tmp_path: Path) -> None:
    _stop(tmp_path, _journal(tmp_path, [_closer(2)]), _down())

    assert _dropped_paths() == []


def test_a_row_dropped_after_two_failed_reviews_leaves_a_ledger_row(tmp_path: Path) -> None:
    _failed_twice(tmp_path, [_closer(2)])

    assert _dropped_paths() == ["note.md"]


def test_a_row_dropped_after_two_failed_reviews_is_not_sent_again(tmp_path: Path) -> None:
    state_root, _response = _failed_twice(tmp_path, [_closer(2)])
    _cooldown_over(state_root)
    later = Provider(AssertionError("must not judge"))

    response = _stop(tmp_path, state_root, later)

    assert response == {}
    assert later.requests == []
    assert _queued_lines(state_root) == []


def test_a_row_with_an_attempt_left_stays_queued_when_an_older_row_is_dropped(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, _down())
    _cooldown_over(state_root)
    session_state.update_state(
        SESSION, lambda state: {**state, journal.STATE_KEY: [*state[journal.STATE_KEY], _closer(3)]}, state_root,
    )

    _stop(tmp_path, state_root, _down())

    assert _queued_lines(state_root) == [3]


def test_a_long_drop_list_names_the_first_rows_and_leaves_out_the_rest(tmp_path: Path) -> None:
    paths = [f"file-{number}.md" for number in range(luna_outage.MAX_NAMED_ROWS + 2)]

    _state_root, response = _failed_twice(tmp_path, [_closer(2, path) for path in paths])

    assert (paths[0] in response["systemMessage"], paths[-1] in response["systemMessage"]) == (True, False)


@pytest.mark.parametrize(("failures", "kept"), [
    pytest.param(0, True, id="untried"),
    pytest.param(1, True, id="one-attempt-left"),
    pytest.param(2, False, id="out-of-attempts"),
])
def test_only_a_row_with_attempts_left_is_retryable(tmp_path: Path, failures: int, kept: bool) -> None:
    state_root, ledger = tmp_path / "state", tmp_path / "ledger"
    row = _closer(2)
    for _attempt in range(failures):
        luna_outage.failed_stop(STOP, [row], DOWN, state_root, ledger)

    assert luna_outage.retryable(STOP, [row], state_root) == ([row] if kept else [])


def test_unreadable_attempts_keep_every_row_retryable(tmp_path: Path) -> None:
    rows = [_closer(2)]

    assert luna_outage.retryable({"session_id": "../outside"}, rows, tmp_path / "state") == rows


def test_an_outage_that_cannot_be_recorded_still_reports_without_blocking(tmp_path: Path) -> None:
    payload = {"session_id": "../outside"}

    response = luna_outage.failed_stop(payload, [_closer(2)], DOWN, tmp_path / "state", tmp_path / "ledger")

    assert "decision" not in response
    assert DOWN in response["systemMessage"]


def test_a_failed_comment_review_tells_the_agent_why(tmp_path: Path) -> None:
    response = claude_luna.run(
        _post_payload(_commented_source(tmp_path)), provider=_down(), state_root=tmp_path / "state", **_luna_paths(tmp_path),
    )

    assert DOWN in response["hookSpecificOutput"]["additionalContext"]


def test_a_comment_review_inside_the_cooldown_returns_nothing_and_does_not_call_luna(tmp_path: Path) -> None:
    source, paths = _commented_source(tmp_path), _luna_paths(tmp_path)
    claude_luna.run(_post_payload(source), provider=_down(), state_root=tmp_path / "state", **paths)
    cooling = Provider(AssertionError("must not judge"))

    response = claude_luna.run(_post_payload(source), provider=cooling, state_root=tmp_path / "state", **paths)

    assert response == {}
    assert cooling.requests == []


def test_a_malformed_verdict_reports_the_failure_without_blocking_the_stop(tmp_path: Path) -> None:
    response = _stop(tmp_path, _journal(tmp_path, [_closer(2)]), _failing("malformed"))

    assert "decision" not in response
    assert DOWN in response["systemMessage"]


def test_a_malformed_verdict_keeps_its_rows_queued(tmp_path: Path) -> None:
    state_root = _journal(tmp_path, [_closer(2)])

    _stop(tmp_path, state_root, _failing("malformed"))

    assert _queued_lines(state_root) == [2]


@pytest.mark.parametrize(("category", "calls"), [
    pytest.param("malformed", 1, id="malformed-retries-at-once"),
    pytest.param("availability", 0, id="availability-cools-down"),
])
def test_only_an_outage_keeps_the_next_stop_from_calling_luna(tmp_path: Path, category: str, calls: int) -> None:
    state_root = _journal(tmp_path, [_closer(2)])
    _stop(tmp_path, state_root, _failing(category))
    later = Provider()

    _stop(tmp_path, state_root, later)

    assert len(later.requests) == calls


def test_a_malformed_comment_verdict_leaves_the_next_comment_review_free_to_call_luna(tmp_path: Path) -> None:
    source, paths = _commented_source(tmp_path), _luna_paths(tmp_path)
    claude_luna.run(_post_payload(source), provider=_failing("malformed"), state_root=tmp_path / "state", **paths)
    later = Provider()

    claude_luna.run(_post_payload(source), provider=later, state_root=tmp_path / "state", **paths)

    assert len(later.requests) == 1
