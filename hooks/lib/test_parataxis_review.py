"""Pinned by behavior, because a parataxis run that never reaches the reviewer flags nothing at runtime."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import record
from lib import claude_luna, claude_native, claude_sonnet, config, journal, parataxis_review, pattern_semantic, session_state
from lib.judge_contracts import JudgeRequest, JudgeResult, ReviewKind, build_prompt
from lib.omp_review_findings import validated_findings
from lib.omp_review_requests import build_work
from lib.pattern_semantic import Exemplar, Layer

ENGLISH_CHAIN = "The hook reads the file. It checks every rule. It writes a report."
GERMAN_CHAIN = "Wir haben eine Pumpe entwickelt. Sie misst den Druck. Sie speichert jeden Wert."
LONG_LEAD = "I traced the slow start to the hook, which reloads its rules on every call and so spends most of its time in the parser."
SESSION = "parataxis"
SECTION_RE = re.compile(r"Section (\d+) \(pattern\)")


def _rows(text: str, path: str = "notes.md", gates: dict | None = None) -> list[dict]:
    return parataxis_review.review_rows(path, text + "\n", {"rule_gates": gates} if gates is not None else {})


def test_a_run_becomes_one_review_row_for_its_language_rule() -> None:
    assert [(row["rule"], row["line"], row["text"]) for row in _rows(ENGLISH_CHAIN)] == [
        ("choppy_sentences", 1, ENGLISH_CHAIN),
    ]


def test_a_german_run_goes_to_the_german_rule() -> None:
    assert [row["rule"] for row in _rows(GERMAN_CHAIN)] == ["de_parataxis"]


def test_the_row_carries_the_sentences_around_the_run() -> None:
    text = _rows(f"{LONG_LEAD} {ENGLISH_CHAIN}")[0]["text"]

    assert text == f"{ENGLISH_CHAIN}\nParagraph: {LONG_LEAD} {ENGLISH_CHAIN}"


@pytest.mark.parametrize("state", ["off", "observe", "enforce"])
def test_only_the_judged_gate_sends_a_run_to_the_reviewer(state: str) -> None:
    assert _rows(ENGLISH_CHAIN, gates={"choppy_sentences": state}) == []


@pytest.mark.parametrize("path,text", [
    pytest.param("tool.py", f"# {ENGLISH_CHAIN}\nVALUE = 1", id="code-comment"),
    pytest.param("notes.md", f"1. {ENGLISH_CHAIN}", id="list-item"),
])
def test_code_comments_and_lists_never_reach_the_reviewer(path: str, text: str) -> None:
    assert _rows(text, path) == []


def test_an_exempt_path_sends_nothing() -> None:
    rows = parataxis_review.review_rows("docs/notes.md", ENGLISH_CHAIN + "\n", {"exempt_paths": ["docs/*"]})

    assert rows == []


def _edits(tmp_path: Path, text: str) -> record._EditJournal:
    (tmp_path / "notes.md").write_text(text + "\n", encoding="utf-8")
    payload = {"session_id": SESSION, "tool_name": "Write", "tool_use_id": "t1", "cwd": str(tmp_path)}
    return record._EditJournal(payload, ["notes.md"], str(tmp_path / "ledger"), str(tmp_path / "state"), {})


def _pattern_rows(tmp_path: Path) -> list[dict]:
    return [row for row in journal.read(SESSION, state_root=str(tmp_path / "state")) if row["role"] == "pattern"]


def test_an_edit_journals_the_run_as_a_pattern_row(tmp_path: Path) -> None:
    record._journal_edits(_edits(tmp_path, ENGLISH_CHAIN), "turn-1")

    assert [(row["rule"], row["text"]) for row in _pattern_rows(tmp_path)] == [("choppy_sentences", ENGLISH_CHAIN)]


def test_a_joined_rewrite_drops_the_pattern_row(tmp_path: Path) -> None:
    record._journal_edits(_edits(tmp_path, ENGLISH_CHAIN), "turn-1")

    record._journal_edits(_edits(tmp_path, "The hook reads the file, checks every rule, and writes a report."), "turn-1")

    assert _pattern_rows(tmp_path) == []


JOINED_A = "The installer copies the hooks into place, and the runtime starts when a hook first needs it."
REWRITTEN_A = "The installer copies the hooks into place, so the runtime starts only when a hook first needs it."


def _second_turn(tmp_path: Path, first: str, second: str) -> list[dict]:
    """A prior turn wrote the first text, because that is how prose becomes inherited for this edit."""
    record._journal_edits(_edits(tmp_path, first), "turn-0")
    record._journal_edits(_edits(tmp_path, second), "turn-1")
    return _pattern_rows(tmp_path)


def test_an_edit_elsewhere_leaves_an_inherited_run_alone(tmp_path: Path) -> None:
    rows = _second_turn(tmp_path, f"{JOINED_A}\n\n{ENGLISH_CHAIN}", f"{REWRITTEN_A}\n\n{ENGLISH_CHAIN}")

    assert rows == []


def test_a_run_written_into_the_edited_paragraph_still_reaches_the_reviewer(tmp_path: Path) -> None:
    rows = _second_turn(tmp_path, f"{JOINED_A}\n\n{ENGLISH_CHAIN}", f"{ENGLISH_CHAIN}\n\n{ENGLISH_CHAIN}")

    assert [(row["line"], row["text"]) for row in rows] == [(1, ENGLISH_CHAIN)]


def test_a_run_over_one_changed_and_one_unchanged_sentence_reaches_the_reviewer(tmp_path: Path) -> None:
    joined = "The hook reads the file.\nIt checks every rule.\nIt writes a report, which the agent reads."

    rows = _second_turn(tmp_path, joined, ENGLISH_CHAIN.replace(". ", ".\n"))

    assert [row["line"] for row in rows] == [1]


def test_an_edit_to_the_sentence_after_an_inherited_run_leaves_the_run_alone(tmp_path: Path) -> None:
    run = ENGLISH_CHAIN.replace(". ", ".\n")

    rows = _second_turn(tmp_path, f"{run}\n{JOINED_A}", f"{run}\n{REWRITTEN_A}")

    assert rows == []


class Judge:  # pylint: disable=too-few-public-methods
    """Because only the pattern verdict is under test, the document section gets no answer."""

    def __init__(self, verdict: str | None) -> None:
        self.verdict = verdict

    def __call__(self, prompt: str) -> str:
        section = int(SECTION_RE.search(prompt).group(1))
        items = [] if self.verdict is None else [{"section": section, "index": 0, "verdict": self.verdict, "reason": "r"}]
        return json.dumps({"type": "result", "is_error": False, "structured_output": {"items": items, "notes": []}})


class LunaVerdicts:  # pylint: disable=too-few-public-methods
    """Because only the pattern verdict is under test, the document gets no note."""

    def judge(self, request: JudgeRequest) -> JudgeResult:
        clean = {"notes": []}
        confirmed = {"items": [{"index": index, "verdict": "violating", "reason": "r"} for index in range(len(request.candidates))]}
        payload = confirmed if request.review_kind is ReviewKind.PATTERN else clean
        return JudgeResult(payload, "openai-codex", "gpt-5.6-luna", "high", request.rubric_version, {})


def _stop(tmp_path: Path, judge: Judge) -> dict:
    record._journal_edits(_edits(tmp_path, ENGLISH_CHAIN), "turn-1")
    state_root = tmp_path / "state"
    session_state.update_state(SESSION, lambda state: {**state, "turn_id": "turn-1"}, state_root)
    stop = {"hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": False, "cwd": str(tmp_path)}
    return claude_sonnet.run(stop, state_root=state_root, judge=judge)


def _assert_join_advice(response: dict) -> None:
    advice = response["hookSpecificOutput"]["additionalContext"]
    assert "decision" not in response
    assert "not a block" in advice
    assert ENGLISH_CHAIN in advice
    assert "(choppy_sentences)" in advice
    assert "a relative clause" in advice
    assert "semicolons stay banned" in advice


def test_a_confirmed_run_tells_the_agent_to_join_without_blocking(tmp_path: Path) -> None:
    _assert_join_advice(_stop(tmp_path, Judge("violating")))


def test_a_run_luna_confirms_tells_the_agent_to_join_without_blocking(tmp_path: Path) -> None:
    record._journal_edits(_edits(tmp_path, ENGLISH_CHAIN), "turn-1")
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    stop = {"hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": False, "cwd": str(tmp_path)}

    response = claude_luna.run(
        stop, provider=LunaVerdicts(), state_root=tmp_path / "state", settings_path=settings, preset_path=preset,
    )

    _assert_join_advice(response)


def test_a_run_the_reviewer_clears_does_not_block(tmp_path: Path) -> None:
    assert _stop(tmp_path, Judge("clean")) == {}


def test_a_skipped_run_reports_that_the_review_did_not_run(tmp_path: Path) -> None:
    response = _stop(tmp_path, Judge(None))

    assert "decision" not in response
    assert "skipped a parataxis run" in response["systemMessage"]


def test_an_omp_confirmed_run_asks_for_a_join_and_not_a_comment_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text(ENGLISH_CHAIN + "\n", encoding="utf-8")
    state_root = str(tmp_path / "state")
    parataxis_review.record(parataxis_review.EditTurn(SESSION, "turn-1", {}, state_root), path)
    work = build_work(path, path.read_text(encoding="utf-8"), {"session_id": SESSION, "state_root": state_root})
    [run] = [item for item in work if item.request.rule_name == "choppy_sentences"]
    verdict = json.dumps({"items": [{"index": 0, "verdict": "violating", "reason": "One thought in three fragments."}]})

    message = " ".join(validated_findings(run, verdict).values())

    assert "a relative clause" in message
    assert "semicolons stay banned" in message
    assert "Rewrite the comment" not in message


def test_the_reviewer_reads_the_definition_and_both_example_sides(tmp_path: Path) -> None:
    record._journal_edits(_edits(tmp_path, ENGLISH_CHAIN), "turn-1")
    rows = journal.read(SESSION, state_root=str(tmp_path / "state"))

    request = next(request for request, _rows in claude_luna.stop_work(rows, {}) if request.review_kind is ReviewKind.PATTERN)

    assert "Definition: Each candidate is a run of short main clauses" in build_prompt(request)
    assert len(request.violating_examples) == len(request.clean_examples) == 4


def test_the_sentence_vote_never_embeds_a_rule_the_scanner_feeds(monkeypatch) -> None:
    monkeypatch.setattr(pattern_semantic, "enabled", lambda: True)
    embedded: list[tuple[Exemplar, ...]] = []
    layer = Layer(
        exemplars=lambda: (Exemplar("choppy_sentences", "violating", ENGLISH_CHAIN),),
        manifest=lambda: {"rules": {"choppy_sentences": {"action": "Join.", "judge_precision": 1.0, "candidates": "static"}}},
        exemplar_vectors=lambda rows: embedded.append(rows) or {},
        vectors=lambda _texts: {},
    )

    assert pattern_semantic.candidates("a.md", ENGLISH_CHAIN + "\n", layer=layer) == {}
    assert embedded == []


@pytest.mark.parametrize("rule", sorted(parataxis_review.RULES))
def test_the_shipped_gate_is_judged_and_its_calibration_matches_the_manifest(rule: str) -> None:
    manifest = pattern_semantic.load_manifest()

    assert config.rule_state(rule) == config.JUDGED_STATE
    assert config.RULE_CALIBRATIONS[rule].precision == manifest["rules"][rule]["judge_precision"]


@pytest.mark.parametrize("rule", sorted(parataxis_review.RULES))
def test_a_reviewer_precision_below_the_bar_never_blocks(rule: str) -> None:
    assert not pattern_semantic.rule_blocks(pattern_semantic.load_manifest(), rule, {})
