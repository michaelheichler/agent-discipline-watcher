from __future__ import annotations

from lib import prose_structure, regex_judge
from lib.pattern_judge import JudgedOutcome
from lib.config import JUDGED_STATE
from lib.scanner import scan_all

FOUR_ITEMS = "The kit ships with a manual, a cable, a charger, and a case."
THREE_ITEMS = "The kit ships with a manual, a cable, and a case."


def test_a_four_item_list_is_not_a_three_item_series() -> None:
    assert not prose_structure._is_three_item_series(FOUR_ITEMS)


def test_a_three_item_list_is_a_three_item_series() -> None:
    assert prose_structure._is_three_item_series(THREE_ITEMS)


def test_the_scan_reports_the_three_item_sentence_and_not_the_four_item_one() -> None:
    text = f"{FOUR_ITEMS}\n\n{THREE_ITEMS}\n"

    lines = [row["line"] for row in scan_all("sample.md", text, {}) if row["rule"] == "three_item_list"]

    assert lines == [3]


def test_three_item_list_reaches_the_judged_gate_rather_than_the_write_path() -> None:
    assert "three_item_list" in regex_judge.judged_rules({})


def test_a_judged_rule_speaks_only_through_the_reader(monkeypatch) -> None:
    findings = [{"rule": "three_item_list", "line": 3, "snippet": THREE_ITEMS}]
    monkeypatch.setattr(
        regex_judge, "confirm_all",
        lambda work, _model: JudgedOutcome(
            {rule.name: candidates for rule, candidates in work if candidates}, (), ""),
    )

    confirmed = regex_judge.confirm("sample.md", findings, {})

    assert [(item.rule, item.line) for item in confirmed] == [("three_item_list", 3)]


def test_a_reader_that_confirms_nothing_reports_nothing(monkeypatch) -> None:
    findings = [{"rule": "three_item_list", "line": 3, "snippet": THREE_ITEMS}]
    monkeypatch.setattr(regex_judge, "confirm_all", lambda _work, _model: JudgedOutcome({}, (), ""))

    assert regex_judge.confirm("sample.md", findings, {}) == ()


def test_an_unjudged_rule_never_reaches_the_reader(monkeypatch) -> None:
    findings = [{"rule": "passive_voice", "line": 1, "snippet": "The build was broken by the change."}]
    monkeypatch.setattr(
        regex_judge, "confirm_all",
        lambda _work, _model: (_ for _ in ()).throw(AssertionError("an enforcing rule was sent to the reader")),
    )

    assert regex_judge.confirm("sample.md", findings, {}) == ()


def test_a_project_can_move_another_rule_to_the_judged_gate() -> None:
    config = {"rule_gates": {"passive_voice": JUDGED_STATE}}

    assert "passive_voice" in regex_judge.judged_rules(config)
