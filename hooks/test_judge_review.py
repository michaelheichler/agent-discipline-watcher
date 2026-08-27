import os
import shutil

import pytest

import judge_review
from lib.hookio import PARSE_FAILURE
from lib.judge import RECURSION_GUARD

NARRATING_SOURCE = (
    "def scan():\n"
    '    """Counts the retries because the report header needs a total before the body renders."""\n'
    "    return []\n"
)


def _payload(path) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


def test_a_broken_payload_wakes_nobody() -> None:
    assert judge_review.run(PARSE_FAILURE) == (0, "")


def test_a_non_python_file_is_left_alone(tmp_path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("Counts the retries because the header needs a total.\n", encoding="utf-8")

    assert judge_review.run(_payload(target)) == (0, "")


def test_a_missing_file_is_left_alone(tmp_path) -> None:
    assert judge_review.run(_payload(tmp_path / "gone.py")) == (0, "")


def test_a_file_without_candidates_never_reaches_the_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(RECURSION_GUARD, "1")
    target = tmp_path / "clean.py"
    target.write_text("def scan():\n    return []\n", encoding="utf-8")

    assert judge_review.run(_payload(target)) == (0, "")


def test_an_unavailable_judge_never_wakes_the_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(RECURSION_GUARD, "1")
    target = tmp_path / "narrating.py"
    target.write_text(NARRATING_SOURCE, encoding="utf-8")

    assert judge_review.run(_payload(target)) == (0, "")


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH")
@pytest.mark.skipif(not os.environ.get("ADW_JUDGE_LIVE"), reason="set ADW_JUDGE_LIVE=1 to spend a model call")
def test_a_narrating_docstring_wakes_the_session(tmp_path) -> None:
    target = tmp_path / "narrating.py"
    target.write_text(NARRATING_SOURCE, encoding="utf-8")

    code, message = judge_review.run(_payload(target))

    assert code == judge_review.WAKE_EXIT_CODE
    assert "Counts the retries" in message
    assert f"{target}:2" in message
