"""Split out because judged pattern work has its own gate contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib.judge_contracts import ReviewKind
from lib.omp_review_requests import build_work
from lib.scanner import scan_all

SERIES = "The kit ships with a manual, a cable, and a case.\n"


def _pattern_blocking(tmp_path: Path, config: dict) -> list[bool]:
    work = build_work(tmp_path / "notes.md", SERIES, config)
    return [item.blocking for item in work if item.request.review_kind is not ReviewKind.DOCUMENT and item.candidates]


def test_the_series_reaches_the_judged_rule() -> None:
    assert "three_item_list" in {finding["rule"] for finding in scan_all("notes.md", SERIES, {})}


@pytest.mark.parametrize(("config", "expected"), (
    ({}, [True]),
    ({"gates": {"english": "observe"}}, [False]),
    ({"rule_gates": {"three_item_list": "observe"}}, []),
))
def test_a_confirmed_judged_finding_follows_the_configured_state(tmp_path: Path, config: dict, expected: list[bool]) -> None:
    assert _pattern_blocking(tmp_path, config) == expected
