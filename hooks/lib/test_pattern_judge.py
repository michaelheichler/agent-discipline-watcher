from __future__ import annotations

import json

import pytest

from lib import pattern_judge
from lib.judge_contracts import ReviewKind
from lib.pattern_judge import PatternCandidate, PatternRule

RULE = PatternRule("ai_closer", "End when the answer is done.", ("Let me know if you need anything else.",), ("The build passed.",))
CANDIDATES = (
    PatternCandidate("a.md", 1, "I hope this helps."),
    PatternCandidate("a.md", 2, "The cache holds 4096 entries."),
)


def _answer(rows: list[dict]) -> str:
    return json.dumps({"result": json.dumps(rows), "is_error": False})


def test_the_prompt_carries_the_rule_its_fix_and_both_example_sides() -> None:
    prompt = pattern_judge.build_prompt(RULE, CANDIDATES)

    assert RULE.name in prompt
    assert RULE.action in prompt
    assert "violating: Let me know if you need anything else." in prompt
    assert "clean: The build passed." in prompt
    assert "0. I hope this helps." in prompt


def test_pattern_candidates_adapt_to_the_shared_judge_contract() -> None:
    request = pattern_judge.request_for(RULE, CANDIDATES)

    assert request.review_kind is ReviewKind.PATTERN
    assert request.rule_name == RULE.name
    assert request.candidates == tuple(candidate.text for candidate in CANDIDATES)


def test_only_the_lines_the_judge_calls_violating_survive(monkeypatch) -> None:
    monkeypatch.setattr(pattern_judge, "available", lambda: True)
    monkeypatch.setattr(
        pattern_judge, "_run",
        lambda _prompt, _model: _answer([{"index": 0, "verdict": "violating"}, {"index": 1, "verdict": "clean"}]),
    )

    assert pattern_judge.confirm(RULE, CANDIDATES, pattern_judge.JUDGED_GATE_MODEL) == (CANDIDATES[0],)


def test_an_index_the_judge_skipped_reads_as_clean() -> None:
    kept = pattern_judge.parse_verdicts(_answer([{"index": 1, "verdict": "violating"}]), 3)

    assert kept == (False, True, False)


def test_an_answer_without_an_array_raises_rather_than_confirming() -> None:
    with pytest.raises(ValueError):
        pattern_judge.parse_verdicts(json.dumps({"result": "no verdict here", "is_error": False}), 1)


def test_an_error_body_raises_rather_than_confirming() -> None:
    with pytest.raises(ValueError):
        pattern_judge.parse_verdicts(json.dumps({"result": "[]", "is_error": True}), 1)


def test_an_absent_judge_confirms_nothing(monkeypatch) -> None:
    monkeypatch.setattr(pattern_judge, "available", lambda: False)

    assert pattern_judge.confirm(RULE, CANDIDATES, pattern_judge.JUDGED_GATE_MODEL) == ()


def test_a_judge_that_never_answers_confirms_nothing(monkeypatch) -> None:
    monkeypatch.setattr(pattern_judge, "available", lambda: True)
    monkeypatch.setattr(pattern_judge, "_run", lambda _prompt, _model: None)

    assert pattern_judge.confirm(RULE, CANDIDATES, pattern_judge.JUDGED_GATE_MODEL) == ()


def test_no_candidates_costs_no_call(monkeypatch) -> None:
    monkeypatch.setattr(pattern_judge, "available", lambda: True)
    monkeypatch.setattr(pattern_judge, "_run", lambda _prompt, _model: pytest.fail("the judge was called with nothing to judge"))

    assert pattern_judge.confirm(RULE, (), pattern_judge.JUDGED_GATE_MODEL) == ()
