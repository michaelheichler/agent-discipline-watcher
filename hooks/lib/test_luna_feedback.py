import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import luna_feedback
from lib.judge import Candidate


@pytest.fixture(name="reports")
def _reports(tmp_path: Path) -> Path:
    return tmp_path / "reports"


def _comments(count: int) -> tuple[tuple[Candidate, ...], SimpleNamespace]:
    found = tuple(Candidate("src/a.py", line, f"# note {line}") for line in range(1, count + 1))
    items = [{"index": index, "verdict": "describes_code", "reason": "Restates the code."} for index in range(count)]
    return found, SimpleNamespace(payload={"items": items})


def test_comment_rows_name_path_line_found_problem_and_action() -> None:
    found, result = _comments(1)
    lines = luna_feedback.comment_feedback(result, found).split("\n")
    assert lines[1] == (
        '1. src/a.py:1 Found "# note 1". Problem: Restates the code. '
        "Action: Rewrite the comment to say why the code exists, or delete it."
    )


def test_comment_rows_cap_at_five_and_point_to_the_report(reports: Path) -> None:
    found, result = _comments(8)
    lines = luna_feedback.comment_feedback(result, found).split("\n")
    assert [line.split(".", 1)[0] for line in lines[1:6]] == ["1", "2", "3", "4", "5"]
    report = next(reports.glob("*.json"))
    assert lines[6] == f"3 more findings: {report}"
    assert len(json.loads(report.read_text(encoding="utf-8"))) == 8


def test_document_rows_carry_the_path_and_line_of_the_quote() -> None:
    rows = [{"path": "docs/a.md", "source_context": "Intro.\nThe release ships soon.\n"}]
    result = SimpleNamespace(payload={"notes": [{"quote": "ships soon", "problem": "Vague date", "fix": "Give the date"}]})
    lines = luna_feedback.document_feedback(result, rows).split("\n")
    assert lines[1] == '1. docs/a.md:2 Found "ships soon". Problem: Vague date. Action: Give the date.'


def test_feedback_stays_inside_the_character_budget(reports: Path) -> None:
    found = tuple(Candidate("src/a.py", line, "#" + "x" * 500) for line in range(1, 8))
    items = [{"index": index, "verdict": "describes_code", "reason": "y" * 500} for index in range(7)]
    text = luna_feedback.comment_feedback(SimpleNamespace(payload={"items": items}), found)
    assert len(text) <= luna_feedback.MAX_FEEDBACK_CHARS
    assert text.endswith(str(next(reports.glob("*.json"))))
