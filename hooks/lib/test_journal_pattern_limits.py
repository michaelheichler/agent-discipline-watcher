"""Retain omitted populations because review must not mistake a bounded journal for completeness."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lib import journal, pattern_vote
from lib.pattern_semantic import Sentence


def document(root: Path, count: int = 100) -> tuple[Path, str, list[dict]]:
    path = root / "sample.md"
    rows = [{"rule": "ai_closer", "line": line, "text": f"Candidate {line}.",
             "severity": "observe"} for line in range(1, count + 1)]
    text = "\n".join(row["text"] for row in rows) + "\n"
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(text.encode()).hexdigest(), rows


@pytest.fixture
def overflowing(tmp_path) -> tuple[Path, Path]:
    path, digest, rows = document(tmp_path)
    state = tmp_path / "state"
    journal.record_patterns("session", "turn", path, rows, content_hash=digest,
                            state_root=state, project=tmp_path)
    return path, state


def test_pattern_truncation_records_the_full_missing_population(tmp_path) -> None:
    path, digest, rows = document(tmp_path)
    state = tmp_path / "state"

    journal.record_patterns("session", "turn", path, rows, content_hash=digest,
                            state_root=state, project=tmp_path)

    stored = journal.read("session", state_root=state)
    marker = journal.read_overflow("session", state_root=state)[0]
    assert len(stored) == journal.MAX_PATTERN_ROWS_PER_FILE
    assert marker["candidate_count"] == len(rows)
    assert marker["pattern_candidate_count"] == len(rows)
    assert marker["omitted_count"] == len(rows) - len(stored)


def test_an_unchanged_edit_cannot_erase_missing_pattern_candidates(tmp_path, overflowing) -> None:
    path, state = overflowing
    before = journal.read_overflow("session", state_root=state)[0]

    journal.record_edit("session", "next-turn", "tool", path, state_root=state, project=tmp_path)

    after = journal.read_overflow("session", state_root=state)[0]
    assert after["pattern_candidate_count"] == before["pattern_candidate_count"]
    assert after["omitted_count"] >= before["omitted_count"]


def test_changed_source_clears_its_stale_pattern_overflow(tmp_path, overflowing) -> None:
    path, state = overflowing
    path.write_text("A corrected note.\n", encoding="utf-8")

    journal.record_edit("session", "next-turn", "tool", path, state_root=state, project=tmp_path)

    assert journal.read_overflow("session", state_root=state) == []


@pytest.mark.parametrize("separate", [False, True])
def test_blocking_patterns_survive_a_full_observe_population(tmp_path, separate) -> None:
    path, digest, rows = document(tmp_path, journal.MAX_PATTERN_ROWS_PER_FILE)
    state = tmp_path / "state"
    block = {"rule": "utilize", "line": len(rows) + 1, "text": "Utilize the receiver.",
             "severity": "block"}
    batches = {False: [rows + [block]], True: [rows, [block]]}[separate]

    record_batches((path, digest), state, batches)

    stored = journal.read("session", state_root=state)
    marker = journal.read_overflow("session", state_root=state)[0]
    assert len(stored) == journal.MAX_PATTERN_ROWS_PER_FILE
    assert block["line"] in {row["line"] for row in stored if row["rule"] == "utilize"}
    assert marker["omitted_count"] == 1


def record_batches(source, state, batches) -> None:
    path, digest = source
    for rows in batches:
        journal.record_patterns("session", "turn", path, rows, content_hash=digest,
                                state_root=state, project=path.parent)


def test_further_eviction_keeps_prior_missing_population(tmp_path, overflowing) -> None:
    path, state = overflowing
    before = journal.read_overflow("session", state_root=state)[0]

    fill_other_documents(tmp_path, state)

    markers = journal.read_overflow("session", state_root=state)
    [after] = [row for row in markers if row.get("path_identity") == str(path)]
    assert after["pattern_candidate_count"] == before["pattern_candidate_count"]
    assert after["omitted_count"] > before["omitted_count"]


def fill_other_documents(project, state) -> None:
    for number in range(journal.MAX_ROWS - journal.MAX_PATTERN_ROWS_PER_FILE + 1):
        path = project / f"other-{number}.md"
        path.write_text("An unrelated note.\n", encoding="utf-8")
        journal.record_edit("session", "turn", "tool", path, state_root=state, project=project)


@pytest.mark.parametrize("rule_gate,expected", [
    pytest.param({}, "block", id="measured-enforce"),
    pytest.param({"utilize": "observe"}, "observe", id="rule-observe"),
])
def test_pattern_votes_journal_the_effective_rule_severity(tmp_path, rule_gate, expected) -> None:
    path, _digest, _rows = document(tmp_path)
    config = {"state_root": str(tmp_path / "state"), "rule_gates": rule_gate}
    turn = pattern_vote.VoteTurn("session", "turn", config, str(tmp_path))
    voter = pattern_vote.Voter(candidates=lambda *_args: {
        "utilize": [Sentence(1, "Utilize the receiver.")],
        "ai_closer": [Sentence(2, "Hope this helps!")],
    })

    rows = pattern_vote.vote(turn, path, voter)

    assert {row["rule"]: row["severity"] for row in rows} == {
        "utilize": expected, "ai_closer": "observe",
    }
