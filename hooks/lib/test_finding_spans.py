"""Pinned by behavior, because a block finding that drops its last line lets an edit inside the block pass as inherited."""
from __future__ import annotations

from typing import NamedTuple

import pytest

from lib import german_rules, test_rules
from lib.findings import Finding
from lib.german_punctuation import DASH_CLUSTER_MIN_COUNT
from lib.scanner import scan_all

ENGLISH_ONLY = {"prose_languages": ["en"]}
GERMAN_ONLY = {"prose_languages": ["de"]}
INTRO = "Intro line here.\n\n"
LONG_SENTENCE = "The scanner reads every file in the project before it writes the report."
GERMAN_SENTENCE = "Der Hund lief heute im Park herum."
GERMAN_PAIR = "Der Hund lief. Die Katze schlief im warmen Haus am Fenster."


class Case(NamedTuple):
    path: str
    text: str
    config: dict
    rule: str
    span: tuple[int, int | None]


def _five_word_sentences() -> str:
    return (
        "The hook reads each file.\n"
        "The scan checks every rule.\n"
        "The gate blocks bad writes.\n"
        "The ledger keeps each row.\n"
    )


def _long_list() -> str:
    items = "".join(f"- Item number {number} goes here\n" for number in range(10))
    return items + "  continued text for the last item\n"


def _short_endings() -> str:
    return "\n".join(f"{LONG_SENTENCE}\nIt {verb}.\n" for verb in ("stops", "waits", "ends"))


def _long_function() -> str:
    body = "".join(f"    v{number} = {number}\n" for number in range(90))
    return "import os\n\ndef big():\n" + body + "    return v0\n"


def _narrating_docstring() -> str:
    return (
        'def f():\n'
        '    """This function first reads the file.\n'
        '    Then it parses every line.\n'
        '    Then it returns the result.\n'
        '    """\n'
        '    return 1\n'
    )


def _dash_cluster() -> str:
    first = " – ".join(["Das ist so"] * DASH_CLUSTER_MIN_COUNT) + "."
    filler = "Wir bauen das Haus und es dauert lange.\n"
    return first + "\n" + filler + filler + "Das bleibt so – weil wir es wollen.\n"


def _uniform_german_rhythm() -> str:
    two = f"{GERMAN_SENTENCE} {GERMAN_SENTENCE}\n"
    return two + two + "\n" + two + two


def _equal_german_paragraphs() -> str:
    return f"{GERMAN_PAIR}\n\n{GERMAN_PAIR}\n\n{GERMAN_PAIR}\n\n" + GERMAN_PAIR.replace(". ", ".\n") + "\n"


def _english_cases() -> dict[str, Case]:
    return {
        "low_sentence_variance": Case(
            "doc.md", INTRO + _five_word_sentences(), dict(ENGLISH_ONLY), "low_sentence_variance", (3, 6)),
        "uniform_paragraph_endings": Case(
            "doc.md", _short_endings(), dict(ENGLISH_ONLY), "uniform_paragraph_endings", (1, 8)),
        "oversized_list-with-continuation": Case(
            "doc.md", INTRO + _long_list(), {**ENGLISH_ONLY, "list_item_cap": 8}, "oversized_list", (3, 13)),
        "three_item_list-markdown-loose": Case(
            "doc.md", INTRO + "- Apples are red\n\n- Pears are green\n\n- Plums are dark\n",
            dict(ENGLISH_ONLY), "three_item_list", (3, 7)),
        "choppy_sentences": Case(
            "doc.md", INTRO + "The hook reads the file.\nIt checks every rule.\nIt writes a report.\n",
            dict(ENGLISH_ONLY), "choppy_sentences", (3, 5)),
    }


def _german_cases() -> dict[str, Case]:
    return {
        "de_repeated_connector": Case(
            "doc.md",
            "Außerdem kam der Hund heute nach Hause.\nAußerdem ging er wieder in den Garten.\n"
            "Außerdem schlief er dort sehr lange.\n",
            dict(GERMAN_ONLY), "de_repeated_connector", (1, 3)),
        "de_uniform_rhythm": Case("doc.md", _uniform_german_rhythm(), dict(GERMAN_ONLY), "de_uniform_rhythm", (1, 5)),
        "de_uniform_paragraphs": Case(
            "doc.md", _equal_german_paragraphs(), dict(GERMAN_ONLY), "de_uniform_paragraphs", (1, 8)),
        "de_long_compound": Case(
            "doc.md", "Der Bericht kam gestern an.\nEr nennt die Donaudampfschifffahrtsgesellschaft.\n",
            dict(GERMAN_ONLY), "de_long_compound", (2, None)),
        "de_parataxis": Case(
            "doc.md", "Wir haben eine Pumpe entwickelt.\nSie misst den Druck.\nSie speichert jeden Wert.\n",
            dict(GERMAN_ONLY), "de_parataxis", (1, 3)),
        "german-registry-de_empty_intensifier": Case(
            "doc.md", "Der Hund kam heute nach Hause.\nEr war sehr müde und schlief dort.\n",
            dict(GERMAN_ONLY), "de_empty_intensifier", (2, None)),
        "dash_cluster": Case("doc.md", _dash_cluster(), dict(GERMAN_ONLY), "dash_cluster", (1, 4)),
    }


def _code_cases() -> dict[str, Case]:
    return {
        "function_too_long": Case(
            "src/mod.py", _long_function(), {"function_block_lines": 80}, "function_too_long", (3, 94)),
        "docstring_narration": Case("src/mod.py", _narrating_docstring(), {}, "docstring_narration", (2, 5)),
        "prose_comment_block-c-block": Case(
            "src/mod.ts",
            "/* This module reads the file\n   and then it parses the lines\n   and returns them all. */\nconst a = 1;\n",
            {}, "prose_comment_block", (1, 3)),
        "prose_comment_block-hash-run": Case(
            "src/mod.py", "x = 1\n# This loop reads every file in turn\n# and then it writes each one back out\ny = 2\n",
            {}, "prose_comment_block", (2, 3)),
    }


def _test_unit_cases() -> dict[str, Case]:
    return {
        "assert_in_loop": Case(
            "tests/test_mod.py", "def test_x():\n    for item in [1, 2]:\n        assert item > 0\n    done = True\n",
            {}, "assert_in_loop", (3, 4)),
        "if_statements_in_tests": Case(
            "tests/test_mod.py",
            "def test_check() -> None:\n    result = sut.check(value)\n    if value > 0:\n"
            "        assert result is True\n    else:\n        assert result is False\n",
            {}, "if_statements_in_tests", (3, 6)),
        "if_statements_in_tests-rust": Case(
            "tests/check.rs",
            "#[test]\nfn check_returns_expected_result() {\n    let result = sut.check(input);\n    if input > 0 {\n"
            "        assert!(result);\n    } else {\n        assert!(!result);\n    }\n}\n",
            {}, "if_statements_in_tests", (4, 9)),
        "multiple_act_sections_in_unit_test": Case(
            "tests/test_mod.py",
            "def test_add_then_remove() -> None:\n    sut.add_item(item)\n    assert sut.item_count == 1\n"
            "    sut.remove_item(item)\n    assert sut.item_count == 0\n",
            {}, "multiple_act_sections_in_unit_test", (4, 5)),
    }


def _span_cases() -> dict[str, Case]:
    return {**_english_cases(), **_german_cases(), **_code_cases(), **_test_unit_cases()}


def _hollow_case() -> Case:
    return Case("tests/test_mod.py", "def test_x():\n    value = compute()\n    print(value)\n", {}, "hollow_test", (1, 3))


def _every_case() -> dict[str, Case]:
    return {**_span_cases(), "hollow_test": _hollow_case()}


def _covered_rules() -> set[str]:
    return {case.rule for case in _every_case().values()}


def _spans(case: Case) -> set[tuple[int, int | None]]:
    rows = scan_all(case.path, case.text, case.config)
    return {(row["line"], row.get("end_line")) for row in rows if row["rule"] == case.rule}


@pytest.mark.parametrize("case", [pytest.param(case, id=name) for name, case in _span_cases().items()])
def test_a_finding_spans_only_the_lines_its_evidence_covers(case: Case) -> None:
    assert _spans(case) == {case.span}


def test_a_hollow_test_finding_reaches_past_the_last_body_line() -> None:
    case = _hollow_case()

    rows = [row for row in scan_all(case.path, case.text, case.config) if row["rule"] == case.rule]

    assert [(row["line"], row["end_line"] >= case.span[1]) for row in rows] == [(case.span[0], True)]


@pytest.mark.parametrize("case", [pytest.param(case, id=name) for name, case in _every_case().items()])
def test_no_finding_ends_before_it_starts(case: Case) -> None:
    rows = scan_all(case.path, case.text, case.config)

    assert [row for row in rows if row.get("end_line") is not None and row["end_line"] < row["line"]] == []


def test_every_rule_that_spans_a_test_unit_has_a_span_case() -> None:
    spanning_rules = {rule.name for rule_set in test_rules.RULE_SETS for rule in rule_set.rules if rule.spans_test}

    assert spanning_rules - _covered_rules() == set()


def test_every_rule_that_reports_a_span_has_a_span_case_outside_the_shared_german_registry() -> None:
    registry = {rule.name for rule in german_rules.declared()}
    reported = {
        row["rule"]
        for case in _every_case().values()
        for row in scan_all(case.path, case.text, case.config)
        if row.get("end_line") is not None
    }

    assert reported - _covered_rules() - registry == set()


def test_a_single_line_finding_carries_no_end_line() -> None:
    rows = [row for row in scan_all("doc.md", "We build the house — and it takes time.\n", {}) if row["rule"] == "banned_dash"]

    assert [("end_line" in row) for row in rows] == [False]


def _finding(line: int, end_line: int | None) -> Finding:
    return Finding(
        family="english", rule="oversized_list", line=line, detail="List exceeds the cap.",
        force=None, snippet="- item", action="Split the list.", path=None, severity=None,
        tool_use_id=None, end_line=end_line,
    )


def test_a_finding_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValueError):
        _finding(5, 4)


def test_end_line_survives_a_dict_round_trip() -> None:
    finding = _finding(3, 13)

    assert Finding.from_dict(finding.to_dict()) == finding
