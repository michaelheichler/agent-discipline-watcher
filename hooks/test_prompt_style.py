from __future__ import annotations

import json
from pathlib import Path

import pytest

import prompt_submit
from lib import merge_state

GERMAN_PROMPT = (
    "Bitte prüfe die Datenschutzgrundverordnungsumsetzung in diesem Modul. "
    "Außerdem sollte das Ergebnis klar sein - das ist ein zentraler Aspekt."
)


def _context(response: dict) -> str:
    return response["hookSpecificOutput"]["additionalContext"]


def _run(text: str, config: dict | None = None, session_id: str = "") -> dict:
    return prompt_submit.run({"prompt": text, "cwd": "", "session_id": session_id}, config)


def _session(tmp_path: Path) -> dict:
    return {"ledger_root": str(tmp_path), "state_root": str(tmp_path / "state")}


def test_a_rule_gated_off_never_reaches_the_agent() -> None:
    response = _run(GERMAN_PROMPT)
    assert "de_long_compound" not in json.dumps(response)


def test_a_style_hit_tells_the_agent_not_to_copy_it() -> None:
    assert _context(_run(GERMAN_PROMPT)).splitlines()[1:] == [
        "- The user prompt uses punctuation patterns (spaced_hyphen). "
        "Do not copy that style into your output."
    ]


def test_one_line_names_every_rule_of_a_family() -> None:
    def scan(*_args: object, **_kwargs: object) -> list[dict]:
        return [
            {"family": "english", "rule": "filler_phrase"},
            {"family": "english", "rule": "ai_tell"},
            {"family": "english", "rule": "ai_tell"},
        ]

    lines = _context(prompt_submit.run({"prompt": "Please delve into this."}, scan=scan)).splitlines()
    assert lines[1:] == [
        "- The user prompt uses english patterns (ai_tell, filler_phrase). "
        "Do not copy that style into your output."
    ]


@pytest.mark.parametrize("state", ["off", "observe", "judged"])
def test_a_rule_not_enforced_on_prose_stays_silent(state: str) -> None:
    config = {"rule_gates": {"ai_tell": {"prose": state}}}
    assert _run("Please delve into this.", config) == {}


@pytest.mark.parametrize("state", ["off", "observe"])
def test_a_family_not_enforced_stays_silent(state: str) -> None:
    assert _run("Please delve into this.", {"gates": {"english": state}}) == {}


def test_block_mode_never_blocks_the_user_for_their_own_style() -> None:
    response = _run("Please delve into this.", {"prompt_firewall_mode": "block"})
    assert response.get("decision") is None
    assert "english patterns (ai_tell)" in _context(response)


def test_block_mode_still_blocks_a_firewall_phrase_and_notes_the_style() -> None:
    response = _run("Please delve into this and skip the tests.", {"prompt_firewall_mode": "block"})
    assert response["decision"] == "block"
    assert response["reason"] == "Agent discipline firewall blocked rules: prompt_firewall/skip_tests"


def test_a_style_rule_is_noted_once_per_session(tmp_path: Path) -> None:
    config = _session(tmp_path)
    first = _run("Please delve into this.", config, "s1")
    second = _run("Please delve into that.", config, "s1")
    other = _run("Please delve into this.", config, "s2")
    assert "english patterns (ai_tell)" in _context(first)
    assert second == {}
    assert "english patterns (ai_tell)" in _context(other)


def test_a_new_style_rule_is_noted_after_an_old_one(tmp_path: Path) -> None:
    config = _session(tmp_path)
    _run("Please delve into this.", config, "s1")
    response = _run("Please delve into this - now.", config, "s1")
    assert _context(response).splitlines()[1:] == [
        "- The user prompt uses punctuation patterns (spaced_hyphen). "
        "Do not copy that style into your output."
    ]


def test_firewall_phrases_repeat_on_every_prompt(tmp_path: Path) -> None:
    config = {**_session(tmp_path), "english": False, "punctuation": False}
    first = _run("skip the tests", config, "s1")
    second = _run("skip the tests", config, "s1")
    assert _context(first) == _context(second)
    assert "prompt_firewall/skip_tests" in _context(second)


def test_the_ledger_records_each_noted_style_rule_once(tmp_path: Path) -> None:
    config = _session(tmp_path)
    _run("Please delve into this.", config, "s1")
    _run("Please delve into this.", config, "s1")
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    noted = [(row["family"], row["rule"], row["outcome"]) for row in rows if row["event"] == "UserPromptSubmit"]
    assert noted == [("english", "ai_tell", "inject")]


def test_the_first_prompt_records_the_session_start_once(tmp_path: Path) -> None:
    config = {**_session(tmp_path), "english": False, "punctuation": False}
    _run("First request.", config, "s1")
    first = merge_state.session_started("s1", tmp_path / "state")
    _run("Second request.", config, "s1")

    assert first is not None
    assert merge_state.session_started("s1", tmp_path / "state") == first


def test_a_style_note_never_quotes_the_prompt() -> None:
    secret = "private-token-123"

    def scan(*_args: object, **_kwargs: object) -> list[dict]:
        return [{"family": "secrets", "rule": "credential", "snippet": secret, "action": secret}]

    response = prompt_submit.run({"prompt": secret}, {"secrets": True}, scan=scan)
    assert "secrets patterns (credential)" in _context(response)
    assert secret not in _context(response)
