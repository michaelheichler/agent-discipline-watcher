import json
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
from lib import review
from testing import init_repo, run_git as _git


def _args(cwd: Path, **overrides) -> Namespace:
    values = {
        "cwd": cwd,
        "paths": [],
        "commits": None,
        "format": "text",
        "output": None,
        "gitnexus": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _repository(path: Path) -> None:
    init_repo(path)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


def test_selected_file_reports_attached_fields_and_project_severity(tmp_path) -> None:
    bad = "wrong" + "\N{EM DASH}" + "break\n"
    source = tmp_path / "sample.md"
    source.write_text(bad, encoding="utf-8")
    (tmp_path / ".agent-discipline.json").write_text(
        json.dumps({"gates": {"punctuation": "observe"}}),
        encoding="utf-8",
    )

    findings, scope, revision, metadata = review.run_review(
        _args(tmp_path, paths=["sample.md"])
    )

    row = next(item for item in findings if item["rule"] == "banned_dash")
    assert row == {
        "rule": "banned_dash",
        "severity": "would_block",
        "path": "sample.md",
        "line": 1,
        "excerpt": bad.strip(),
        "hint": "Use ASCII hyphen or rewrite the sentence.",
    }
    assert (scope, revision, metadata) == ("selected paths", "working tree", None)


def test_selected_directory_expands_files_and_output_file_is_written(tmp_path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "bad.md").write_text("bad" + "\N{EM DASH}" + "line\n", encoding="utf-8")
    output = tmp_path / "report.json"
    args = _args(tmp_path, paths=["docs"], format="json", output=output)

    status = review.emit(args)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert status == 1
    assert payload["v"] == 1
    assert payload["f"][0][2] == "docs/bad.md"


def test_repository_directory_scope_excludes_ignored_files(tmp_path) -> None:
    _repository(tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "tracked.md").write_text("plain text\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("docs/ignored.md\n", encoding="utf-8")
    _commit(tmp_path, "tracked files")
    (folder / "ignored.md").write_text(
        "bad" + "\N{EM DASH}" + "line\n",
        encoding="utf-8",
    )

    findings, _, _, _ = review.run_review(_args(tmp_path, paths=["docs"]))

    assert findings == []


def test_full_scope_outside_repository_has_actionable_error(tmp_path) -> None:
    with pytest.raises(ValueError, match="Pass one or more paths"):
        review.run_review(_args(tmp_path))


def test_commit_scope_uses_head_content_and_new_side_lines_only(tmp_path) -> None:
    _repository(tmp_path)
    source = tmp_path / "sample.md"
    old_bad = "old" + "\N{EM DASH}" + "break"
    new_bad = "new" + "\N{EM DASH}" + "break"
    source.write_text(f"{old_bad}\nplain\n", encoding="utf-8")
    _commit(tmp_path, "initial")
    source.write_text(f"{old_bad}\nplain\n{new_bad}\n", encoding="utf-8")
    _commit(tmp_path, "violation")
    expected_revision = _git(tmp_path, "rev-parse", "HEAD")
    source.write_text("working tree no longer matches head\n", encoding="utf-8")

    findings, scope, revision, _ = review.run_review(_args(tmp_path, commits=1))

    banned = [item for item in findings if item["rule"] == "banned_dash"]
    assert [(item["line"], item["excerpt"]) for item in banned] == [(3, new_bad)]
    assert scope == "last 1 commits"
    assert revision == expected_revision


def test_commit_scope_still_reports_line_one_anchored_rules(tmp_path) -> None:
    _repository(tmp_path)
    source = tmp_path / "big.py"
    lines = [f"value_{number} = {number}" for number in range(1300)]
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _commit(tmp_path, "initial")
    lines[600] = "value_600 = 601"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _commit(tmp_path, "edit line 601")

    findings, _, _, _ = review.run_review(_args(tmp_path, commits=1))

    assert any(item["rule"] == "file_too_long" for item in findings)


def test_commit_scope_takes_precedence_over_positional_paths(tmp_path) -> None:
    _repository(tmp_path)
    source = tmp_path / "sample.md"
    source.write_text("clean\n", encoding="utf-8")
    _commit(tmp_path, "initial")
    source.write_text("still clean\n", encoding="utf-8")
    _commit(tmp_path, "change")

    findings, scope, _, _ = review.run_review(
        _args(tmp_path, commits=1, paths=["missing.md"])
    )

    assert findings == []
    assert scope == "last 1 commits"


def test_hunk_parser_uses_new_ranges_and_ignores_zero_length_hunks() -> None:
    patch_text = "\n".join(
        [
            "+++ b/a.py",
            "@@ -2,0 +3,2 @@",
            "@@ -8,2 +10,0 @@",
            "+++ b/b.py",
            "@@ -1 +4 @@",
        ]
    )

    assert review._parse_ranges(patch_text) == {
        "a.py": [(3, 4)],
        "b.py": [(4, 4)],
    }


def test_short_history_error_names_shallow_or_short_repository(tmp_path) -> None:
    _repository(tmp_path)
    (tmp_path / "sample.md").write_text("clean\n", encoding="utf-8")
    _commit(tmp_path, "initial")

    with pytest.raises(ValueError, match="shallow or shorter"):
        review.run_review(_args(tmp_path, commits=3))


def test_gitnexus_success_uses_existing_runner_output(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "gitnexus"
    executable.write_text("#!/bin/sh\nprintf 'indexed graph ready\\n'\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert review._gitnexus(tmp_path) == "gitnexus: indexed graph ready"


def test_gitnexus_degradation_states(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "")
    assert review._gitnexus(tmp_path) == "gitnexus: unavailable"

    with patch("lib.review.shutil.which", return_value="/tmp/gitnexus"):
        with patch(
            "lib.review.subprocess.run",
            side_effect=subprocess.TimeoutExpired("gitnexus", 2),
        ):
            assert review._gitnexus(tmp_path) == "gitnexus: stale"
        failed = subprocess.CompletedProcess(
            args=["gitnexus", "status"], returncode=3, stdout="", stderr="index missing\n",
        )
        with patch("lib.review.subprocess.run", return_value=failed):
            assert review._gitnexus(tmp_path) == "gitnexus: error (exit 3): index missing"
        with patch(
            "lib.review.subprocess.run",
            side_effect=FileNotFoundError("gitnexus vanished"),
        ):
            assert review._gitnexus(tmp_path) == "gitnexus: error (gitnexus vanished)"


def test_gitnexus_metadata_does_not_change_review_status(tmp_path, monkeypatch, capsys) -> None:
    source = tmp_path / "clean.md"
    source.write_text("plain text\n", encoding="utf-8")
    monkeypatch.setenv("PATH", "")

    status = review.emit(_args(tmp_path, paths=["clean.md"], gitnexus=True))

    assert status == 0
    assert "gitnexus: unavailable" in capsys.readouterr().out
