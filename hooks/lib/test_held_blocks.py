"""Real files and journal state here, because a held verdict must keep blocking exactly as long as its flagged file stays unchanged."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import claude_luna, claude_sonnet, journal, session_state

SESSION = "held"
CLOSER = "Feel free to ask me anything else."
SAME_FILE = "I hope this helps with your project."
LATE = "Do not hesitate to reach out."
EDITED = "Reach out whenever another question comes up."
NOTE_LINES = {2: CLOSER, 5: SAME_FILE, 9: LATE}
CLOSER_VOTE = {"rule": "ai_closer", "line": 2, "text": CLOSER}
SAME_FILE_VOTE = {"rule": "ai_closer", "line": 5, "text": SAME_FILE}
SAME_LINE_VOTE = {"rule": "utilize", "line": 2, "text": CLOSER}
LATE_VOTE = {"rule": "ai_closer", "line": 9, "text": LATE}
GATES = {"rule_gates": {"ai_closer": "enforce", "utilize": "enforce"}}
OBSERVED = {"rule_gates": {"ai_closer": "observe"}}
EMPTY_VERDICT = json.dumps({"type": "result", "is_error": False, "structured_output": {"items": [], "notes": []}})
VIOLATING = json.dumps({
    "type": "result", "is_error": False,
    "structured_output": {"items": [{"section": 0, "index": 0, "verdict": "violating", "reason": "Stock closer."}], "notes": []},
})
Indexes = tuple[int, ...]
# Past the 128 KiB read cap, so no capped read can confirm the old text.
OVERSIZED = "A plain line without the flagged sentence.\n" * 4000


@pytest.fixture(autouse=True)
def _enforce_both_rules(tmp_path: Path) -> None:
    """Enforced, because the shipped default only observes these rules and an observed rule holds nothing."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(GATES), encoding="utf-8")


def _payload(tmp_path: Path, active: bool = False) -> dict:
    return {"hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": active, "cwd": str(tmp_path)}


def _note(tmp_path: Path) -> Path:
    target = tmp_path / "note.md"
    target.write_text("".join(f"{NOTE_LINES.get(line, f'Plain line {line}.')}\n" for line in range(1, 10)), encoding="utf-8")
    return target


def _vote(state_root: Path, target: Path, votes: list[dict]) -> None:
    """Hashed from the file on disk, because the journal keeps a vote only for the text it was cast on."""
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    journal.record_patterns(SESSION, "turn-1", target, votes, content_hash=digest, state_root=state_root, project=target.parent)


def _queued(tmp_path: Path, votes: list[dict]) -> Path:
    state_root = tmp_path / "state"
    session_state.write_state(SESSION, {"turn_id": "turn-1"}, state_root)
    _vote(state_root,_note(tmp_path), votes)
    return state_root


def _requests(tmp_path: Path, state_root: Path) -> dict[str, tuple]:
    work = claude_luna.stop_work(claude_luna.stop_rows(_payload(tmp_path), state_root), GATES)
    return {request.rule_name: (request, sources) for request, sources in work}


def _uphold(tmp_path: Path, state_root: Path, verdicts: list[tuple]) -> None:
    claude_luna.remember_blocks(_payload(tmp_path), verdicts, GATES, state_root)


def _uphold_each_time(tmp_path: Path, state_root: Path, times: int) -> None:
    request, rows = _requests(tmp_path, state_root)["ai_closer"]
    for number in range(times):
        _uphold(tmp_path, state_root, [(request, f"Held verdict {number}", rows)])


def _held(tmp_path: Path, state_root: Path) -> list[str]:
    return claude_luna.held_blocks(_payload(tmp_path), state_root)


def _stop(tmp_path: Path, state_root: Path) -> dict:
    """An empty verdict, so any block in the reply comes from a held verdict."""
    return claude_sonnet.run(_payload(tmp_path), state_root=state_root, judge=lambda _prompt: EMPTY_VERDICT)


def _held_by_a_review(tmp_path: Path) -> tuple[Path, Path]:
    """Held through a real Stop, because that Stop also marks the row answered the way a live session does."""
    state_root = _queued(tmp_path, [CLOSER_VOTE])
    claude_sonnet.run(_payload(tmp_path), state_root=state_root, judge=lambda _prompt: VIOLATING)
    return tmp_path / "note.md", state_root


def _sonnet_active_stop(tmp_path: Path, state_root: Path, calls: list) -> dict:
    return claude_sonnet.run(_payload(tmp_path, active=True), state_root=state_root, judge=lambda prompt: calls.append(prompt) or EMPTY_VERDICT)


def _luna_active_stop(tmp_path: Path, state_root: Path, calls: list) -> dict:
    return claude_luna.run(_payload(tmp_path, active=True), provider=SimpleNamespace(judge=calls.append), state_root=state_root)


def _bulk_votes(tmp_path: Path, state_root: Path, files: range) -> None:
    votes = [{"rule": "ai_closer", "line": line, "text": f"Vote {line}"} for line in range(1, journal.MAX_PATTERN_ROWS_PER_FILE + 1)]
    for number in files:
        target = tmp_path / f"bulk-{number}.md"
        target.write_text(f"Bulk file {number}.\n", encoding="utf-8")
        _vote(state_root,target, votes)


def test_upholding_one_row_many_times_in_a_turn_holds_one_verdict_and_still_blocks(tmp_path: Path) -> None:
    state_root = _queued(tmp_path, [CLOSER_VOTE])
    _uphold_each_time(tmp_path, state_root, journal.MAX_ROWS + 10)

    response = _stop(tmp_path, state_root)

    assert response.get("decision") == "block"
    assert len(_held(tmp_path, state_root)) == 1


def test_two_rules_on_one_line_keep_their_own_held_verdicts(tmp_path: Path) -> None:
    state_root = _queued(tmp_path, [CLOSER_VOTE, SAME_LINE_VOTE])
    closer, utilize = (_requests(tmp_path, state_root)[rule] for rule in ("ai_closer", "utilize"))
    _uphold(tmp_path, state_root, [(closer[0], "Closer verdict", closer[1])])
    _uphold(tmp_path, state_root, [(utilize[0], "Utilize verdict", utilize[1])])

    _uphold(tmp_path, state_root, [(closer[0], "Closer verdict again", closer[1])])

    assert sorted(_held(tmp_path, state_root)) == ["Closer verdict again", "Utilize verdict"]


@pytest.mark.parametrize(("renewed", "expected"), [
    pytest.param((0,), ["Newer verdict 0", "Verdict on both rows"], id="one-row-renewed"),
    pytest.param((0, 1), ["Newer verdict 0", "Newer verdict 1"], id="both-rows-renewed"),
])
def test_a_newer_verdict_replaces_the_older_one_only_on_its_own_rows(tmp_path: Path, renewed: Indexes, expected: list[str]) -> None:
    state_root = _queued(tmp_path, [CLOSER_VOTE, SAME_FILE_VOTE])
    request, rows = _requests(tmp_path, state_root)["ai_closer"]
    _uphold(tmp_path, state_root, [(request, "Verdict on both rows", rows)])

    _uphold(tmp_path, state_root, [(request, f"Newer verdict {index}", [rows[index]]) for index in renewed])

    assert sorted(_held(tmp_path, state_root)) == expected


@pytest.mark.parametrize(("follow_up", "gates"), [
    pytest.param(lambda request, rows: [], GATES, id="no-verdict"),
    pytest.param(lambda request, rows: [(request, "Clean verdict", [])], GATES, id="no-violating-row"),
    pytest.param(lambda request, rows: [(request, "", rows)], GATES, id="empty-text"),
    pytest.param(lambda request, rows: [(request, "Observed verdict", rows)], OBSERVED, id="observed-rule"),
])
def test_an_uphold_that_holds_nothing_keeps_the_existing_block(tmp_path: Path, follow_up, gates: dict) -> None:
    state_root = _queued(tmp_path, [CLOSER_VOTE])
    request, rows = _requests(tmp_path, state_root)["ai_closer"]
    _uphold(tmp_path, state_root, [(request, "Closer verdict", rows)])

    claude_luna.remember_blocks(_payload(tmp_path), follow_up(request, rows), gates, state_root)

    assert _held(tmp_path, state_root) == ["Closer verdict"]


def test_a_verdict_for_a_row_that_is_not_queued_does_not_hold_it_once_it_arrives(tmp_path: Path) -> None:
    state_root = _queued(tmp_path, [CLOSER_VOTE])
    request, rows = _requests(tmp_path, state_root)["ai_closer"]
    _uphold(tmp_path, state_root, [(request, "Verdict before the row arrived", [{**rows[0], "line": 9, "text": LATE}])])

    _vote(state_root,tmp_path / "note.md", [LATE_VOTE])

    assert _held(tmp_path, state_root) == []


def test_a_held_row_pushed_out_of_a_full_journal_still_blocks_the_turn(tmp_path: Path) -> None:
    state_root = _queued(tmp_path, [CLOSER_VOTE])
    _uphold_each_time(tmp_path, state_root, 1)
    _bulk_votes(tmp_path, state_root, range(journal.MAX_ROWS // journal.MAX_PATTERN_ROWS_PER_FILE + 1))

    response = _stop(tmp_path, state_root)

    assert response.get("decision") == "block"


def test_a_journal_full_of_held_rows_still_blocks_when_another_vote_arrives(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    session_state.write_state(SESSION, {"turn_id": "turn-1"}, state_root)
    _bulk_votes(tmp_path, state_root, range(journal.MAX_ROWS // journal.MAX_PATTERN_ROWS_PER_FILE))
    request, rows = _requests(tmp_path, state_root)["ai_closer"]
    _uphold(tmp_path, state_root, [(request, f"Verdict {index}", [row]) for index, row in enumerate(rows)])
    _vote(state_root,_note(tmp_path), [CLOSER_VOTE])

    response = _sonnet_active_stop(tmp_path, state_root, [])

    assert response.get("decision") == "block"


ACTIVE_STOPS = [pytest.param(_sonnet_active_stop, id="sonnet"), pytest.param(_luna_active_stop, id="luna")]


def _later_mtime(target: Path) -> None:
    status = target.stat()
    os.utime(target, (status.st_atime + 60, status.st_mtime + 60))


@pytest.mark.parametrize("active_stop", ACTIVE_STOPS)
@pytest.mark.parametrize("change", [
    pytest.param(lambda target: None, id="unchanged"),
    pytest.param(_later_mtime, id="mtime-only"),
])
def test_a_held_block_still_blocks_an_active_stop_without_a_model_call(tmp_path: Path, change, active_stop) -> None:
    target, state_root = _held_by_a_review(tmp_path)
    change(target)
    calls: list = []

    response = active_stop(tmp_path, state_root, calls)

    assert response.get("decision") == "block"
    assert calls == []


@pytest.fixture(name="readable_note_afterwards")
def _readable_note_afterwards(tmp_path: Path):
    """Restored, so that the temporary directory stays removable after a test locks the note."""
    yield
    (tmp_path / "note.md").chmod(0o644)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whose mode is 000")
@pytest.mark.usefixtures("readable_note_afterwards")
@pytest.mark.parametrize("active_stop", ACTIVE_STOPS)
def test_a_held_file_that_turns_unreadable_still_blocks_an_active_stop_without_a_model_call(tmp_path: Path, active_stop) -> None:
    target, state_root = _held_by_a_review(tmp_path)
    target.chmod(0o000)
    calls: list = []

    response = active_stop(tmp_path, state_root, calls)

    assert response.get("decision") == "block"
    assert calls == []


@pytest.mark.parametrize("active_stop", ACTIVE_STOPS)
@pytest.mark.parametrize("change", [
    pytest.param(Path.unlink, id="deleted"),
    pytest.param(lambda target: target.write_text(f"{EDITED}\n", encoding="utf-8"), id="edited"),
    pytest.param(lambda target: target.write_text(OVERSIZED, encoding="utf-8"), id="oversized-utf8"),
    pytest.param(lambda target: target.write_bytes(b"\xff\xfe\xfd not utf-8\n"), id="not-utf8"),
])
def test_a_changed_held_file_releases_the_block_on_the_next_stop(tmp_path: Path, change, active_stop) -> None:
    target, state_root = _held_by_a_review(tmp_path)
    change(target)
    calls: list = []

    response = active_stop(tmp_path, state_root, calls)

    assert "decision" not in response
    assert calls == []


def test_an_edited_held_file_gets_a_fresh_review_on_the_next_regular_stop(tmp_path: Path) -> None:
    target, state_root = _held_by_a_review(tmp_path)
    target.write_text(f"{EDITED}\n", encoding="utf-8")
    _vote(state_root,target, [{"rule": "ai_closer", "line": 1, "text": EDITED}])
    prompts: list[str] = []

    response = claude_sonnet.run(_payload(tmp_path), state_root=state_root, judge=lambda prompt: prompts.append(prompt) or EMPTY_VERDICT)

    assert "decision" not in response
    assert [EDITED in prompt for prompt in prompts] == [True]
