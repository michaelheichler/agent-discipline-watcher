from __future__ import annotations

import json

import pytest

import read_claude_journal
from lib import pattern_semantic

PATTERN = {
    "role": "pattern", "path": "/work/notes.md", "content_hash": "abc", "rule": "ai_closer",
    "line": 3, "text": "Feel free to ask me anything else.",
}
DOCUMENT = {"role": "document", "path": "/work/notes.md", "content_hash": "abc", "source_context": "Body."}


@pytest.fixture(name="served")
def _served(monkeypatch) -> list[list[dict]]:
    marked: list[list[dict]] = []
    monkeypatch.setattr(read_claude_journal, "mark_reviewed", lambda _session, rows: marked.append(rows))
    return marked


def _output(capsys) -> list[dict]:
    return json.loads(capsys.readouterr().out)


def test_each_rule_in_the_rows_arrives_with_four_examples_per_side(monkeypatch, capsys, served) -> None:
    monkeypatch.setattr(read_claude_journal, "read_for_stop", lambda _session: [PATTERN, {**PATTERN, "line": 4}])
    expected = pattern_semantic.rule_prompt(
        "ai_closer", pattern_semantic.load_exemplars(), pattern_semantic.load_manifest(),
    )

    read_claude_journal.main(["session"])

    rules = [row for row in _output(capsys) if row["role"] == "rule"]
    assert rules == [{
        "role": "rule", "rule": "ai_closer", "action": expected.action,
        "violating": list(expected.violating_examples), "clean": list(expected.clean_examples),
    }]
    assert len(rules[0]["violating"]) == len(rules[0]["clean"]) == 4
    assert served == [[PATTERN, {**PATTERN, "line": 4}]]


def test_rows_without_a_pattern_carry_no_examples(monkeypatch, capsys, served) -> None:
    monkeypatch.setattr(read_claude_journal, "read_for_stop", lambda _session: [])
    monkeypatch.setattr(read_claude_journal, "load_exemplars", lambda: pytest.fail("loaded exemplars"))

    read_claude_journal.main(["session"])

    assert _output(capsys) == []
    assert served == [[]]


def test_a_rule_without_a_rubric_is_served_without_examples(monkeypatch, capsys, served) -> None:
    unknown = {**PATTERN, "rule": "retired_rule"}
    monkeypatch.setattr(read_claude_journal, "read_for_stop", lambda _session: [unknown])

    read_claude_journal.main(["session"])

    assert _output(capsys) == [unknown]
    assert served == [[unknown]]


def test_document_rows_pass_through_unchanged(monkeypatch, capsys, served) -> None:
    monkeypatch.setattr(read_claude_journal, "read_for_stop", lambda _session: [DOCUMENT])

    read_claude_journal.main(["session"])

    assert _output(capsys) == [DOCUMENT]
    assert served == [[DOCUMENT]]
