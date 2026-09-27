from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import read_claude_journal
from lib import claude_presets, pattern_semantic

PATTERN = {
    "role": "pattern", "path": "/work/notes.md", "content_hash": "abc", "rule": "ai_closer",
    "line": 3, "text": "Feel free to ask me anything else.",
}
DOCUMENT = {"role": "document", "path": "/work/notes.md", "content_hash": "abc", "source_context": "Body."}


@pytest.fixture(name="served")
def _served() -> list[list[dict]]:
    return []


def _serve(argv: list[str], stored: list[dict], served: list[list[dict]], **seams: object) -> int:
    return read_claude_journal.main(
        argv, read=lambda _session: stored, mark=lambda _session, rows: served.append(rows), **seams,
    )


def _output(capsys) -> list[dict]:
    return json.loads(capsys.readouterr().out)


def test_each_rule_in_the_rows_arrives_with_four_examples_per_side(capsys, served) -> None:
    expected = pattern_semantic.rule_prompt(
        "ai_closer", pattern_semantic.load_exemplars(), pattern_semantic.load_manifest(),
    )

    _serve(["session"], [PATTERN, {**PATTERN, "line": 4}], served)

    rules = [row for row in _output(capsys) if row["role"] == "rule"]
    assert rules == [{
        "role": "rule", "rule": "ai_closer", "action": expected.action,
        "violating": list(expected.violating_examples), "clean": list(expected.clean_examples),
    }]
    assert len(rules[0]["violating"]) == len(rules[0]["clean"]) == 4
    assert served == [[PATTERN, {**PATTERN, "line": 4}]]


def test_rows_without_a_pattern_carry_no_examples(capsys, served) -> None:
    _serve(["session"], [], served, exemplar_source=lambda: pytest.fail("loaded exemplars"))

    assert _output(capsys) == []
    assert served == [[]]


def test_a_rule_without_a_rubric_is_served_without_examples(capsys, served) -> None:
    unknown = {**PATTERN, "rule": "retired_rule"}

    _serve(["session"], [unknown], served)

    assert _output(capsys) == [unknown]
    assert served == [[unknown]]


def test_document_rows_arrive_only_when_asked_for(capsys, served) -> None:
    _serve(["session"], [DOCUMENT], served)
    _serve([claude_presets.DOCUMENTS_FLAG, "session"], [DOCUMENT], served)

    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line) for line in lines] == [[], [DOCUMENT]]
    assert served == [[], [DOCUMENT]]


def test_the_shell_helper_passes_the_documents_flag_through(tmp_path) -> None:
    reader = Path(read_claude_journal.__file__).with_name("read_claude_journal.sh")
    result = subprocess.run(
        [str(reader), claude_presets.DOCUMENTS_FLAG, "session"], env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == "[]"


def test_the_retired_stand_down_flag_is_refused() -> None:
    """Refused, because no shipped reviewer asks any more."""
    with pytest.raises(SystemExit) as refused:
        read_claude_journal.main(["--superseded"])

    assert refused.value.code == 2
