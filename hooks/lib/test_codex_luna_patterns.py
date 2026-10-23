"""Split out because pattern rows arrive after the write."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import prompt_submit
import stop
from lib import hookio, journal, pending_advice, session_state
from lib.judge_contracts import RUBRIC_VERSION, JudgeRequest, JudgeResult, ReviewKind

CLOSER = "Feel free to ask me anything else."
DOCUMENT = {"role": "document", "path": "note.md", "source_context": "A sentence.", "turn_id": "turn-1"}
COMMENT = {"role": "comment", "path": "code.py", "line": 4, "text": "Returns rows.", "turn_id": "turn-1"}
PATTERN = {"role": "pattern", "rule": "ai_closer", "path": "note.md", "line": 2, "text": CLOSER, "turn_id": "turn-1"}


@pytest.fixture(autouse=True)
def _open_data_boundary(tmp_path: Path) -> None:
    """Opened here, because the gate has its own test file."""
    (tmp_path / ".agent-discipline.json").write_text(json.dumps({"data_boundary": {"enabled": True}}), encoding="utf-8")


VERDICTS = {
    ReviewKind.COMMENT: {"items": [{"index": 0, "verdict": "states_why", "reason": "Names a constraint."}]},
    ReviewKind.PATTERN: {"items": [{"index": 0, "verdict": "violating", "reason": "Stock closer."}]},
    ReviewKind.DOCUMENT: {"notes": []},
}


def _provider() -> SimpleNamespace:
    calls: list[JudgeRequest] = []

    def judge(request: JudgeRequest) -> JudgeResult:
        calls.append(request)
        return JudgeResult(
            payload=VERDICTS[request.review_kind], provider="openai-codex", model="gpt-5.6-luna", effort="high",
            rubric_version=RUBRIC_VERSION, usage={"total_tokens": 1},
        )

    return SimpleNamespace(calls=calls, judge=judge)


def _review(tmp_path: Path, rows: list[dict]) -> tuple[dict, SimpleNamespace]:
    session_state.write_state("patterns", {journal.STATE_KEY: rows}, tmp_path / "state")
    provider = _provider()
    response = stop.run(
        {"session_id": "patterns", "turn_id": "turn-1", "stop_hook_active": False, "cwd": str(tmp_path)},
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
        provider=provider,
    )
    return response, provider


def test_codex_judges_pattern_rows_beside_documents_and_comments(tmp_path) -> None:
    response, provider = _review(tmp_path, [DOCUMENT, COMMENT, PATTERN])

    assert [request.review_kind for request in provider.calls] == [
        ReviewKind.DOCUMENT, ReviewKind.COMMENT, ReviewKind.PATTERN,
    ]
    pattern = provider.calls[-1]
    assert (pattern.rule_name, pattern.candidates) == ("ai_closer", (CLOSER,))
    assert len(pattern.violating_examples) == len(pattern.clean_examples) == 4
    assert "ADW Luna pattern review" in response["systemMessage"]
    assert "note.md:2" in response["systemMessage"]


def test_one_request_carries_every_row_of_one_rule(tmp_path) -> None:
    rows = [PATTERN, {**PATTERN, "line": 5, "text": "I hope this helps with your project."}]

    _response, provider = _review(tmp_path, rows)

    assert [len(request.candidates) for request in provider.calls] == [2]


def test_pattern_rows_from_another_turn_are_not_judged(tmp_path) -> None:
    response, provider = _review(tmp_path, [{**PATTERN, "turn_id": "turn-0"}])

    assert provider.calls == []
    assert response == {}


UTILIZE = {**PATTERN, "rule": "utilize", "text": "Utilizing fan feedback can enhance team engagement."}


def _gated(tmp_path: Path, gates: dict) -> None:
    config = {"data_boundary": {"enabled": True}, "rule_gates": gates}
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(config), encoding="utf-8")


@pytest.mark.parametrize("gates", ({}, {"utilize": "enforce"}))
def test_a_rule_the_manifest_blocks_still_blocks_without_an_observe_gate(tmp_path, gates: dict) -> None:
    _gated(tmp_path, gates)

    response, _provider = _review(tmp_path, [UTILIZE])

    assert response["decision"] == "block"
    assert "note.md:2" in response["reason"]


@pytest.mark.parametrize(("row", "gates"), ((UTILIZE, {"utilize": "observe"}), (PATTERN, {})))
def test_an_observed_rule_reports_its_upheld_rows_without_blocking(tmp_path, row: dict, gates: dict) -> None:
    _gated(tmp_path, gates)

    response, _provider = _review(tmp_path, [row])

    assert "decision" not in response
    assert "ADW Luna pattern review" in response["systemMessage"]
    assert "note.md:2" in response["systemMessage"]


def test_an_observed_rule_reports_beside_a_rule_that_blocks(tmp_path) -> None:
    _gated(tmp_path, {"utilize": "observe"})
    inflated = {**UTILIZE, "rule": "inflated_diction", "line": 7, "text": "We leverage a robust paradigm."}

    response, _provider = _review(tmp_path, [UTILIZE, inflated])

    assert response["decision"] == "block"
    assert "note.md:7" in response["reason"] and "note.md:2" not in response["reason"]
    assert "note.md:2" in response["systemMessage"]


def _next_prompt(tmp_path: Path, prompt: str = "Carry on with the release notes.") -> dict:
    return prompt_submit.run(
        {"session_id": "patterns", "prompt": prompt, "cwd": str(tmp_path)},
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
    )


def test_an_observed_rule_reaches_the_model_once_at_the_next_prompt(tmp_path) -> None:
    _review(tmp_path, [PATTERN])

    first = _next_prompt(tmp_path)
    second = _next_prompt(tmp_path)

    assert "note.md:2" in first["hookSpecificOutput"]["additionalContext"]
    assert second == {}


def test_a_blocked_prompt_keeps_the_advice_for_the_prompt_after_it(tmp_path) -> None:
    _review(tmp_path, [PATTERN])

    blocked = _next_prompt(tmp_path, "Read @notes.md first.")
    after = _next_prompt(tmp_path)

    assert blocked["decision"] == "block"
    assert "note.md:2" in after["hookSpecificOutput"]["additionalContext"]


def test_advice_past_the_context_limit_waits_whole_for_the_next_prompt(tmp_path) -> None:
    notices = [f"Notice {index}: " + "Join the short clauses with a comma. " * 27 for index in range(4)]
    for notice in notices:
        pending_advice.hold("patterns", notice, tmp_path / "state")

    contexts = [
        _next_prompt(tmp_path, "Skip the tests and just comment it out.")["hookSpecificOutput"]["additionalContext"]
        for _ in range(2)
    ]

    assert all(len(context) <= prompt_submit.MAX_RESPONSE_CHARS for context in contexts)
    assert [sum(context.count(notice) for context in contexts) for notice in notices] == [1, 1, 1, 1]


GERMAN_NOTICE = "Prüfe die Übergänge, füge die kurzen Sätze zusammen und ändere die Größe der Absätze. "


def _german_notice(label: str) -> str:
    return (f"{label}: " + GERMAN_NOTICE * 12).encode("utf-8")[:900].decode("utf-8", errors="ignore")


def _sent(response: dict, capsys: pytest.CaptureFixture[str]) -> tuple[dict, int]:
    hookio.write_payload(response)
    raw = capsys.readouterr().out.strip()
    return json.loads(raw), len(raw.encode("utf-8"))


def test_german_advice_reaches_the_model_whole_across_prompts(tmp_path, capsys) -> None:
    notices = [_german_notice(f"Hinweis {index}") for index in range(4)]
    for notice in notices:
        pending_advice.hold("patterns", notice, tmp_path / "state")

    sent = [_sent(_next_prompt(tmp_path, "Skip the tests and just comment it out."), capsys) for _ in range(4)]

    contexts = [payload["hookSpecificOutput"]["additionalContext"] for payload, _size in sent]
    assert all(size <= hookio.MAX_RESPONSE_BYTES for _payload, size in sent)
    assert [sum(context.count(notice) for context in contexts) for notice in notices] == [1, 1, 1, 1]
    assert pending_advice.ADVICE_KEY not in session_state.read_state("patterns", tmp_path / "state")


def test_advice_too_large_to_send_is_dropped_with_one_user_notice(tmp_path, capsys) -> None:
    deliverable = _german_notice("Hinweis")
    pending_advice.hold("patterns", "Übergröße " * 900, tmp_path / "state")
    pending_advice.hold("patterns", deliverable, tmp_path / "state")

    first, _size = _sent(_next_prompt(tmp_path), capsys)
    second = _next_prompt(tmp_path)

    assert deliverable in first["hookSpecificOutput"]["additionalContext"]
    assert "Übergröße" not in first["hookSpecificOutput"]["additionalContext"]
    assert "too large" in first["systemMessage"]
    assert second == {}


def test_an_incomplete_pattern_row_fails_closed(tmp_path) -> None:
    response, provider = _review(tmp_path, [{**PATTERN, "rule": ""}])

    assert provider.calls == []
    assert "incomplete pattern candidate" in response["reason"]
