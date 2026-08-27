import json
from pathlib import Path

from lib.config import JUDGED_STATE, RULE_CALIBRATIONS, RuleCalibration, effective_config, resolve_outcome
from lib.corpus_gate import requires_corpora
from lib.scanner import scan_all
from lib.slop_harness import (
    Measurement,
    MetricFloor,
    PartitionedMeasurement,
    Surface,
    _rule_scopes,
    assert_floors,
    held_out_measurement,
    score_rule,
    score_rule_partitions,
)


REGEX_JUDGE_PATH = Path(__file__).resolve().parents[2] / "evals" / "regex_judge.json"


def _precision_gate_state(precision: float) -> str:
    if precision >= 0.90:
        return "enforce"
    if precision >= 0.70:
        return "observe"
    return "off"


def _single_corpus_gate_state(calibration: RuleCalibration) -> str:
    if calibration.sample_kind == JUDGED_STATE:
        return JUDGED_STATE
    if calibration.sample_kind == "unmeasurable":
        return "observe"
    state = _precision_gate_state(calibration.precision)
    if state == "enforce":
        return "observe"
    return state


NEW_RULE_STATES = {
    rule: _single_corpus_gate_state(calibration)
    for rule, calibration in RULE_CALIBRATIONS.items()
}


def _calibration_measurement(
    rule: str, calibration: RuleCalibration
) -> Measurement:
    scope = _rule_scopes()[rule]
    if calibration.sample_kind == "held-out":
        result, = score_rule_partitions(rule, scope, (Surface.PROSE,))
        assert isinstance(result, PartitionedMeasurement)
        return held_out_measurement(result)
    if calibration.sample_kind == "in-sample":
        result, = score_rule(rule, scope, (Surface.PROSE,))
        assert isinstance(result, Measurement)
        return result
    if calibration.sample_kind in ("unmeasurable", JUDGED_STATE):
        return None
    raise AssertionError(f"Unsupported calibration sample kind: {calibration.sample_kind}")


def _recorded_judged_stage(rule: str) -> dict:
    record = json.loads(REGEX_JUDGE_PATH.read_text(encoding="utf-8"))
    return record["rules"][rule]


def _integration_text() -> str:
    dense_markers = " ".join(["synergy"] * 8 + ["plain"] * 142) + "."
    return "\n\n".join((
        "In a world where teams must adapt, the work continues.",
        "Have you ever wondered what lies beyond our galaxy?",
        dense_markers,
        "That means that the measured result changed.",
        "Ultimately, the team shipped the release.",
        "This is not a draft, but a released design.",
        "That wasn't the intended result.",
        "History often repeats itself in surprising ways.",
        "Some people believe the change is inevitable.",
        "The deployment was delayed overnight.",
        "Cats watch birds. Dogs chase balls. Fish swim slowly. Bees gather pollen.",
        "The plan covers speed, cost, and quality.",
    ))


def test_scan_all_wires_phrase_structure_and_rhythm_rules() -> None:
    findings = scan_all("sample.md", _integration_text())
    rules = {row["rule"] for row in findings}
    expected = {
        "weighted_slop_marker",
        "formulaic_opener",
        "formulaic_filler",
        "low_sentence_variance",
        "three_item_list",
    }
    assert expected <= rules
    details = {row["rule"]: row["detail"] for row in findings}
    assert all("Calibration:" in details[rule] and "n=" in details[rule] for rule in expected)
    assert all("held-out" in details[rule] for rule in ("weighted_slop_marker", "formulaic_opener", "formulaic_filler"))
    assert "unmeasurable" in details["low_sentence_variance"]
    assert JUDGED_STATE in details["three_item_list"]


def test_english_switch_disables_new_rules() -> None:
    rules = {row["rule"] for row in scan_all("sample.md", _integration_text(), {"english": False})}
    assert not rules & set(NEW_RULE_STATES)


@requires_corpora
def test_recorded_calibrations_do_not_overstate_harness_measurements() -> None:
    for rule, calibration in RULE_CALIBRATIONS.items():
        measured = _calibration_measurement(rule, calibration)
        if calibration.sample_kind == JUDGED_STATE:
            stage = _recorded_judged_stage(rule)
            assert stage["regex_candidates"] == calibration.sample_size
            assert stage["true_positive"] == calibration.true_positive
            assert stage["precision"] >= calibration.precision
            continue
        if measured is None:
            assert calibration.sample_kind == "unmeasurable"
            assert calibration.true_positive == 0
            continue
        precision = measured.counts.precision.value

        assert precision is not None
        assert measured.corpus == calibration.corpus
        assert measured.counts.sample_size == calibration.sample_size
        assert measured.counts.true_positive >= calibration.true_positive
        if calibration.true_positive > 0:
            floor = MetricFloor(calibration.precision, 0.0)
            assert_floors((measured,), {Surface.PROSE: floor})
        else:
            assert precision >= calibration.precision


def test_new_rules_use_their_calibrated_gate_states() -> None:
    gates = effective_config({})["rule_gates"]
    assert {rule: gates[rule] for rule in NEW_RULE_STATES} == NEW_RULE_STATES
    outcomes = {
        rule: resolve_outcome({"family": "english", "rule": rule})
        for rule in NEW_RULE_STATES
    }
    assert all(outcomes[rule] == "would_block" for rule, state in NEW_RULE_STATES.items() if state == "observe")
    assert all(outcomes[rule] == "release" for rule, state in NEW_RULE_STATES.items() if state == "off")
