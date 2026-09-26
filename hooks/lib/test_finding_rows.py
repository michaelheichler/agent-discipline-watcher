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
    assert reporting.format_row(_finding()) == f'notes.md:3 {title} "navigate the". Name the action.'


def test_row_keeps_the_rule_id_out_of_the_reader_text() -> None:
    row = reporting.format_row(_finding())
    assert "business_jargon" not in row
    assert "english/" not in row


def test_row_without_a_match_omits_the_quotes() -> None:
    finding = _finding(rule="file_length_critical")
    del finding["match"]
    title = catalog.rule_entry("file_length_critical").title
    assert reporting.format_row(finding) == f"notes.md:3 {title}. Name the action."


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


def test_row_keeps_the_status_prefix() -> None:
    assert reporting.format_row(_finding(status="removed")).startswith("[removed] notes.md:3 ")
