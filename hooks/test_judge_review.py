import os
import shutil

import pytest

import judge_review
from lib.hookio import PARSE_FAILURE
from lib.judge import RECURSION_GUARD
from lib.judge import Candidate, Verdict

NARRATING_SOURCE = (
    "def scan():\n"
    '    """Counts the retries because the report header needs a total before the body renders."""\n'
    "    return []\n"
)


def _payload(path) -> dict:
    return {"cwd": str(path.parent), "tool_name": "Write", "tool_input": {"file_path": str(path)}}

def test_a_broken_payload_wakes_nobody() -> None:
    assert judge_review.run(PARSE_FAILURE) == (0, "")


def test_a_non_python_file_is_left_alone(tmp_path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("Counts the retries because the header needs a total.\n", encoding="utf-8")

    assert judge_review.run(_payload(target)) == (0, "")


def test_a_missing_file_is_left_alone(tmp_path) -> None:
    assert judge_review.run(_payload(tmp_path / "gone.py")) == (0, "")

def test_a_symlink_outside_the_project_is_left_alone(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text(NARRATING_SOURCE, encoding="utf-8")
    link = project / "linked.py"
    link.symlink_to(outside)

    assert judge_review.run(_payload(link)) == (0, "")


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
def test_default_data_boundary_skips_all_model_reviews(tmp_path, monkeypatch) -> None:
    target = tmp_path / "narrating.py"
    target.write_text(NARRATING_SOURCE, encoding="utf-8")
    monkeypatch.setattr(judge_review, "judge", lambda *_args: pytest.fail("model review launched"))
    monkeypatch.setattr(judge_review, "confirm_judged", lambda *_args: pytest.fail("pattern review launched"))

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


def test_comment_judge_message_sanitizes_candidate_and_reason() -> None:
    verdict = Verdict(Candidate("safe\n\u0085.py", 1, "text\u001b[31m"), True, "reason\u202e")
    message = judge_review._message((verdict,))

    assert "\u001b" not in message
    assert "\u0085" not in message
    assert "\u202e" not in message
    assert "safe  .py:1: text [31m" in message
    assert "(reason )" in message
