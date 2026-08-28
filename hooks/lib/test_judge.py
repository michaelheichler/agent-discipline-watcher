import os
import shutil

import pytest

from lib import judge
from lib.judge_contracts import ReviewKind
from lib.judge import Candidate

# Held apart from the examples in the system prompt, because a candidate copied from the prompt would test recall of the prompt.
CANDIDATES = (
    Candidate("a.py", 2, "Counts the retries because the report header needs a total before the body renders."),
    Candidate("a.py", 9, "Capped at 300 because a longer request times out on the slower of the two hosts."),
)


def test_the_prompt_numbers_every_candidate() -> None:
    prompt = judge.build_prompt(CANDIDATES)

    assert "0. Counts the retries" in prompt
    assert "1. Capped at 300" in prompt


def test_comment_candidates_adapt_to_the_shared_judge_contract() -> None:
    request = judge.request_for(CANDIDATES)

    assert request.review_kind is ReviewKind.COMMENT
    assert request.candidates == tuple(candidate.text for candidate in CANDIDATES)


def test_verdicts_bind_back_to_their_candidate() -> None:
    answer = '[{"index": 1, "verdict": "states_why", "reason": "names a measured limit"}]'

    verdicts = judge.parse_verdicts(answer, CANDIDATES)

    assert len(verdicts) == 1
    assert verdicts[0].candidate.line == 9
    assert verdicts[0].narrates is False


def test_an_out_of_range_index_is_dropped_rather_than_crashing() -> None:
    answer = (
        '[{"index": 7, "verdict": "describes_code", "reason": "out of range"},'
        ' {"index": 0, "verdict": "describes_code", "reason": "opens on a behaviour verb"}]'
    )

    verdicts = judge.parse_verdicts(answer, CANDIDATES)

    assert [item.candidate.line for item in verdicts] == [2]


def test_an_unknown_verdict_word_is_dropped() -> None:
    answer = '[{"index": 0, "verdict": "maybe", "reason": "unsure"}]'

    assert judge.parse_verdicts(answer, CANDIDATES) == ()


def test_an_answer_without_an_array_raises() -> None:
    with pytest.raises(ValueError):
        judge.parse_verdicts("I could not decide.", CANDIDATES)


def test_an_errored_run_raises_rather_than_reporting_a_clean_file() -> None:
    with pytest.raises(ValueError):
        judge._result_text('{"is_error": true, "result": "boom"}')


def test_the_subprocess_drops_the_api_key_and_carries_the_guard(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-spent")

    environment = judge._environment()

    assert "ANTHROPIC_API_KEY" not in environment
    assert environment[judge.RECURSION_GUARD] == "1"


def test_the_guard_stops_a_nested_judge(monkeypatch) -> None:
    monkeypatch.setenv(judge.RECURSION_GUARD, "1")

    assert judge.available() is False
    assert judge.judge(CANDIDATES) is None


def test_no_candidate_needs_no_model() -> None:
    assert judge.judge(()) == ()


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH")
@pytest.mark.skipif(not os.environ.get("ADW_JUDGE_LIVE"), reason="set ADW_JUDGE_LIVE=1 to spend a model call")
def test_the_live_judge_separates_narration_from_a_decision() -> None:
    verdicts = judge.judge(CANDIDATES)

    assert verdicts is not None
    by_line = {item.candidate.line: item.narrates for item in verdicts}
    assert by_line[2] is True
    assert by_line[9] is False
