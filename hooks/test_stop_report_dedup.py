import json
from pathlib import Path

import pytest

import stop
from lib import blocker_state, reporting


def test_stop_reports_each_file_length_finding_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports = tmp_path / "reports"
    monkeypatch.setattr(reporting, "_reports_dir", lambda: reports)
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    paths = [tmp_path / "first.py", tmp_path / "second.py"]
    for number, source in enumerate(paths):
        source.write_text(f"value = {number}\n" * 1000, encoding="utf-8")
    blocker_state.touch_paths("dedup", "", [str(source) for source in paths], config["state_root"])

    response = stop.run({"session_id": "dedup", "cwd": str(tmp_path)}, config)
    report_path = response["reason"].split("Full report: ", 1)[1]
    rows = json.loads(Path(report_path).read_text(encoding="utf-8"))

    assert response["decision"] == "block"
    assert [(row["path"], row["line"], row["rule"]) for row in rows] == [
        (str(source), 1, "file_too_long") for source in paths
    ]


def test_same_content_hash_preserves_distinct_line_findings() -> None:
    rows = [
        {"path": "source.py", "rule": "what_comment", "line": line, "snippet": text, "content_hash": "same"}
        for line, text in [(1, "Returns rows"), (3, "Reads rows")]
    ]

    assert reporting._deduplicated(rows + rows) == rows
