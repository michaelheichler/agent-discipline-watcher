import json
from pathlib import Path

from lib import reporting
from lib.findings import Finding
from lib.scanner import scan_all

UTILIZE = "util" + "ize"
EM_DASH = chr(0x2014)


def _first(path: str, text: str, rule: str) -> dict:
    return next(row for row in scan_all(path, text, {}) if row["rule"] == rule)


def test_english_findings_store_the_matched_span_beside_the_whole_line() -> None:
    text = f"Teams {UTILIZE} the cache here, and the rest is fine"
    finding = _first("notes.md", text + "\n", "utilize")
    assert finding["snippet"] == text
    assert finding["match"] == UTILIZE


def test_punctuation_findings_store_the_matched_span() -> None:
    text = f"Keep the cache{EM_DASH}then read it later"
    finding = _first("notes.md", text + "\n", "banned_dash")
    assert finding["snippet"] == text
    assert finding["match"] == EM_DASH


def test_structure_findings_store_the_matched_span() -> None:
    text = "Some people believe the cache is slow."
    finding = _first("notes.md", text + "\n", "narrator_distance")
    assert finding["snippet"] == text
    assert finding["match"] == "Some people believe"


def test_match_survives_a_dict_round_trip() -> None:
    row = {
        "family": "english", "rule": "utilize", "line": 1, "detail": "d",
        "snippet": "We " + UTILIZE + " it", "action": "Use 'use'.", "match": UTILIZE,
    }
    assert Finding.from_dict(row).to_dict()["match"] == UTILIZE


def test_full_report_keeps_the_matched_span() -> None:
    finding = {
        "path": "a.md", "line": 2, "family": "english", "rule": "utilize",
        "action": "Use 'use'.", "snippet": "We " + UTILIZE + " it", "match": UTILIZE,
    }

    report = reporting.write_full_report([finding], {})

    assert json.loads(Path(report).read_text(encoding="utf-8"))[0]["match"] == UTILIZE
