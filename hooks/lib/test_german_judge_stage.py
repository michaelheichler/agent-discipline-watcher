"""The German gate reads these numbers, because a precision that counts exemplars or ignores sample size would let a weak rule block."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from lib import pattern_semantic
from lib.judge_contracts import GERMAN_RUBRIC_VERSION

EVALS = Path(__file__).resolve().parents[2] / "evals"
RULE = "de_passive_voice"


def _evals_module(name: str) -> ModuleType:
    """Imported by name, because the eval scripts import their siblings by name and not as a package."""
    if str(EVALS) not in sys.path:
        sys.path.insert(0, str(EVALS))
    return importlib.import_module(name)


stage = _evals_module("measure_judge_stage_de")


def _row(line: int, violating: bool, text: str = "") -> object:
    return stage.Row(line, text or f"Satz {line} wird geprüft.", violating)


def _judge_saying(verdicts: dict[str, str], seen: list) -> object:
    def judge(request) -> SimpleNamespace:
        seen.append(request)
        items = [{"index": index, "verdict": verdicts.get(text, "clean")} for index, text in enumerate(request.candidates)]
        return SimpleNamespace(payload={"items": items})
    return judge


def test_all_confirmed_true_still_stays_under_the_bar_on_a_small_sample() -> None:
    assert stage.wilson_lower(9, 9) < 0.85
    assert stage.recommendation(stage.wilson_lower(9, 9)) == "observe"


def test_a_large_clean_sample_earns_enforce() -> None:
    assert stage.recommendation(stage.wilson_lower(60, 60)) == "enforce"


def test_precision_counts_only_confirmed_rows_and_recall_only_violating_ones() -> None:
    rows = [_row(1, True), _row(2, True), _row(3, False), _row(4, False)]

    scored = stage.score(rows, [True, False, True, False])

    assert (scored["precision"], scored["recall"], scored["confirmed"]) == (0.5, 0.5, 2)


def test_nothing_confirmed_reports_no_precision_and_a_zero_bound() -> None:
    scored = stage.score([_row(1, True)], [False])

    assert scored["precision"] is None
    assert scored["precision_lower_bound"] == 0.0


def test_the_judge_receives_the_german_rubric_and_the_shipped_examples() -> None:
    seen: list = []

    stage.judged(RULE, [_row(1, True)], _judge_saying({}, seen))

    assert seen[0].rubric_version == GERMAN_RUBRIC_VERSION
    assert seen[0].rule_name == RULE
    assert len(seen[0].violating_examples) == pattern_semantic.JUDGE_EXAMPLES


def test_rows_split_into_batches_the_judge_answers_in_order() -> None:
    rows = [_row(line, line % 2 == 0) for line in range(1, 46)]
    seen: list = []

    verdicts = stage.judged(RULE, rows, _judge_saying({row.text: "violating" for row in rows if row.violating}, seen))

    assert [len(request.candidates) for request in seen] == [20, 20, 5]
    assert verdicts == [row.violating for row in rows]


def test_an_exemplar_sentence_never_counts_toward_precision() -> None:
    shown = next(row.text for row in pattern_semantic.load_exemplars() if row.rule == RULE and row.label == "violating")
    rows = [_row(1, True, shown), _row(2, True), _row(3, False)]

    measured = stage.measure(RULE, rows, _judge_saying({shown: "violating"}, []))

    assert measured["after_judge"]["candidates"] == 2
    assert measured["all_candidates"]["candidates"] == 3


def test_a_request_resolving_another_luna_stops_the_run() -> None:
    def judge(_request) -> SimpleNamespace:
        return SimpleNamespace(model="gpt-5.6-luna", payload={"items": [{"index": 0, "verdict": "clean"}]})

    with pytest.raises(stage.ModelMismatch):
        stage.judged(RULE, [_row(1, True)], stage.pinned(judge, "gpt-6-luna"))


def test_the_gate_reads_the_highest_luna_run() -> None:
    runs = {"gpt-6-luna": {RULE: "six"}, "gpt-5.6-luna": {RULE: "five six"}}

    assert stage.newest_run(runs) == {RULE: "six"}


def test_a_judge_that_skips_a_candidate_is_refused() -> None:
    def judge(_request) -> SimpleNamespace:
        return SimpleNamespace(payload={"items": []})

    with pytest.raises(ValueError):
        stage.judged(RULE, [_row(1, True)], judge)
