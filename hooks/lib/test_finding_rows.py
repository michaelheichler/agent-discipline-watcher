import pytest

from lib import catalog, reporting, scanner

UTILIZE = "util" + "ize"


def _finding(**extra: object) -> dict:
    return {
        "path": "notes.md", "line": 3, "family": "english", "rule": "business_jargon",
        "action": "Name the action.", "snippet": "We navigate the options", "match": "navigate the",
        **extra,
    }


def test_row_shows_path_line_title_quoted_match_and_action() -> None:
    title = catalog.rule_entry("business_jargon").title
    expected = f'notes.md:3 {title} "navigate the". Name the action. (business_jargon)'
    assert reporting.format_row(_finding()) == expected


def test_row_puts_the_rule_id_last_without_the_family() -> None:
    row = reporting.format_row(_finding())
    assert row.endswith("(business_jargon)")
    assert "english/" not in row


def test_row_without_a_match_omits_the_quotes() -> None:
    finding = _finding(rule="file_length_critical")
    del finding["match"]
    title = catalog.rule_entry("file_length_critical").title
    assert reporting.format_row(finding) == f"notes.md:3 {title}. Name the action. (file_length_critical)"


def test_row_clips_a_long_match() -> None:
    row = reporting.format_row(_finding(match="x" * 400))
    assert len(row) < 200


def test_every_scanner_line_rule_has_a_written_title() -> None:
    names = {row[2] for row in scanner.PUNCTUATION_RULES} | {row[1] for row in scanner.ENGLISH_RULES}
    names |= {"function_too_long", "hollow_test"}
    written = set(catalog.RULES) | set(catalog.UNGATED_RULES)
    readability = {row[1] for row in scanner.READABILITY_RULES}
    assert sorted(names - written - readability) == []


def test_ungated_titles_stay_distinct_from_gated_titles() -> None:
    gated = {entry.title for entry in catalog.RULES.values()}
    ungated = [entry.title for entry in catalog.UNGATED_RULES.values()]
    assert len(ungated) == len(set(ungated))
    assert not gated & set(ungated)
    assert not set(catalog.RULES) & set(catalog.UNGATED_RULES)


@pytest.fixture(name="reports")
def _reports(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reporting, "_reports_dir", lambda: tmp_path)


@pytest.mark.usefixtures("reports")
def test_compact_block_numbers_the_rows() -> None:
    reason, report = reporting.compact_block([_finding(line=1), _finding(line=2)], {})
    lines = reason.split("\n")
    assert lines[1].startswith("1. notes.md:1 ")
    assert lines[2].startswith("2. notes.md:2 ")
    assert lines[3] == "Full report: " + report


@pytest.mark.usefixtures("reports")
def test_compact_block_caps_at_five_and_points_to_the_report() -> None:
    findings = [_finding(line=line) for line in range(1, 9)]
    reason, report = reporting.compact_block(findings, {"max_rows": 8})
    lines = reason.split("\n")
    assert [line.split(".", 1)[0] for line in lines[1:6]] == ["1", "2", "3", "4", "5"]
    assert lines[6] == f"3 more findings: {report}"
    assert len(lines) == 7


@pytest.mark.usefixtures("reports")
def test_long_rows_cannot_push_the_report_path_out() -> None:
    findings = [_finding(line=line, action="y" * 3000) for line in range(1, 9)]
    reason, report = reporting.compact_block(findings, {"max_rows": 8})
    assert len(reason.encode("utf-8")) <= reporting.MAX_COMPACT_BYTES
    assert reason.endswith(report)


def test_row_keeps_the_status_prefix() -> None:
    assert reporting.format_row(_finding(status="removed")).startswith("[removed] notes.md:3 ")
