"""Split out because judged pattern work has its own gate contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import journal, omp_review_requests
from lib.judge_contracts import ReviewKind
from lib.omp_review_requests import build_work
from lib.scanner import scan_all

SERIES = "The kit ships with a manual, a cable, and a case.\n"
CLOSER = "Feel free to ask me anything else."


def _pattern_work(work: tuple) -> list:
    return [item for item in work if item.request.review_kind is ReviewKind.PATTERN]


def _journaled(tmp_path: Path, extra: dict | None = None) -> tuple[Path, dict]:
    path = tmp_path / "notes.md"
    path.write_text(f"{CLOSER}\n", encoding="utf-8")
    source = journal.current_source(path)
    assert source is not None
    state_root = tmp_path / "state"
    journal.record_patterns(
        "omp", "turn", path, [{"rule": "ai_closer", "line": 1, "text": CLOSER}],
        content_hash=source[0], state_root=state_root,
    )
    return path, {"session_id": "omp", "state_root": str(state_root), **(extra or {})}


def test_the_series_reaches_the_judged_rule() -> None:
    assert "three_item_list" in {finding["rule"] for finding in scan_all("notes.md", SERIES, {})}


def test_pattern_work_comes_from_the_journal_rows_for_the_path(tmp_path: Path) -> None:
    path, config = _journaled(tmp_path)

    [item] = _pattern_work(build_work(path, path.read_text(encoding="utf-8"), config))

    assert item.request.rule_name == "ai_closer"
    assert [(candidate.line, candidate.text) for candidate in item.candidates] == [(1, CLOSER)]
    assert len(item.request.violating_examples) == len(item.request.clean_examples) == 4
    assert not item.blocking, "ai_closer ships at observe"


def test_rows_for_other_text_never_become_work(tmp_path: Path) -> None:
    path, config = _journaled(tmp_path)
    other = tmp_path / "other.md"
    other.write_text(f"{CLOSER}\n", encoding="utf-8")

    assert _pattern_work(build_work(other, f"{CLOSER}\n", config)) == []
    assert _pattern_work(build_work(path, "The cache holds 4096 entries.\n", config)) == []


@pytest.mark.parametrize(("gate", "expected"), (("enforce", [True]), ("observe", [False]), ("off", [])))
def test_a_voted_rule_follows_its_rule_gate(tmp_path: Path, gate: str, expected: list[bool]) -> None:
    path, config = _journaled(tmp_path, {"rule_gates": {"ai_closer": gate}})

    work = _pattern_work(build_work(path, path.read_text(encoding="utf-8"), config))

    assert [item.blocking for item in work] == expected


def test_a_session_id_no_journal_can_hold_yields_no_pattern_work(tmp_path: Path) -> None:
    path, config = _journaled(tmp_path, {"session_id": str(tmp_path)})

    assert _pattern_work(build_work(path, path.read_text(encoding="utf-8"), config)) == []


def test_a_judged_rule_with_exemplars_no_longer_reads_regex_hits(tmp_path: Path) -> None:
    assert _pattern_work(build_work(tmp_path / "notes.md", SERIES, {})) == []


@pytest.mark.parametrize(("config", "expected"), (
    ({}, [True]),
    ({"gates": {"english": "observe"}}, [False]),
    ({"rule_gates": {"three_item_list": "observe"}}, []),
))
def test_a_judged_rule_without_exemplars_keeps_the_regex_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: dict, expected: list[bool],
) -> None:
    shipped = omp_review_requests.load_exemplars()
    monkeypatch.setattr(
        omp_review_requests, "load_exemplars",
        lambda: tuple(row for row in shipped if row.rule != "three_item_list"),
    )

    work = _pattern_work(build_work(tmp_path / "notes.md", SERIES, config))

    assert [item.blocking for item in work] == expected
