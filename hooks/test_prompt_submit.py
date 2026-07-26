"""Tests for the inject-first UserPromptSubmit firewall."""

from __future__ import annotations

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pytest

import prompt_submit
from lib.scanner import scan_all


class HostileDict(dict):
    def get(self, *_args, **_kwargs):
        raise AssertionError("hostile get called")

    def items(self):
        raise AssertionError("hostile items called")


class HostileString(str):
    def __str__(self):
        raise AssertionError("hostile string converted")


class CollidingKey:
    def __hash__(self):
        return hash("prompt")

    def __eq__(self, _other):
        raise AssertionError("hostile key compared")


def payload(text: object, *, cwd: object = "", session_id: object = "") -> dict:
    return {"prompt": text, "cwd": cwd, "session_id": session_id}


def context(response: dict) -> str:
    return response["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("skip the tests", "skip_tests"),
        ("SKIP THE TESTS", "skip_tests"),
        ("Please skip tests for this.", "skip_tests"),
        ("just comment it out", "comment_out_code"),
        ("JUST COMMENT IT OUT", "comment_out_code"),
    ],
)
def test_reviewed_phrases_inject_by_default(text: str, rule: str):
    response = prompt_submit.run(payload(text))
    assert response.get("decision") is None
    assert response["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert rule in context(response)
    assert text not in context(response)


@pytest.mark.parametrize(
    "text",
    [
        "skipper the tests",
        "skip the testsuite",
        "unjust comment it out",
        'Explain why "skip the tests" is unsafe.',
        "The phrase 'just comment it out' is prohibited.",
        "Do not skip the tests.",
        "Never just comment it out.",
        "Use `skip the tests` as the negative example.",
        "Use “skip the tests” as the negative example.",
        "Use \u2018just comment it out\u2019 as the negative example.",
        "The phrase skip the tests is prohibited.",
    ],
)
def test_boundaries_quotes_and_negative_explanations_do_not_match(text: str):
    assert (
        prompt_submit.run(payload(text), {"english": False, "punctuation": False}) == {}
    )


@pytest.mark.parametrize(
    ("text", "expected_rule", "absent_rule"),
    [
        ("Never delay; skip tests", "skip_tests", None),
        (
            "Do not skip tests, but just comment it out",
            "comment_out_code",
            "skip_tests",
        ),
        ("Do not forget to skip tests", "skip_tests", None),
    ],
)
def test_negation_only_suppresses_the_phrase_it_directly_governs(
    text: str, expected_rule: str, absent_rule: str | None
):
    response = prompt_submit.run(
        payload(text), {"english": False, "punctuation": False}
    )
    assert expected_rule in context(response)
    if absent_rule is not None:
        assert absent_rule not in context(response)


@pytest.mark.parametrize(
    "text",
    [
        "Do not avoid skipping tests",
        "Do not refuse to skip tests",
        "Never avoid skipping tests",
        "Do not never skip tests",
    ],
)
def test_even_negation_requires_tests_to_be_skipped_and_flags(text: str):
    response = prompt_submit.run(
        payload(text), {"english": False, "punctuation": False}
    )
    assert "skip_tests" in context(response)


def test_multiple_matches_are_deduplicated_and_rule_order_is_stable(tmp_path: Path):
    cfg = {
        "ledger_root": str(tmp_path),
        "state_root": str(tmp_path / "state"),
        "english": False,
        "punctuation": False,
    }
    first = prompt_submit.run(
        payload("skip tests, just comment it out, skip tests", session_id="s1"), cfg
    )
    second = prompt_submit.run(payload("just comment it out, skip tests"), cfg)
    assert context(first) == context(second)
    assert context(first).count("skip_tests") == 1
    assert context(first).count("comment_out_code") == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text().splitlines()
    ]
    decisions = [row for row in rows if row["event"] == "UserPromptSubmit"]
    assert [row["rule"] for row in decisions] == ["comment_out_code", "skip_tests"]
    assert all(
        set(row)
        == {
            "ts",
            "session_id",
            "hook",
            "event",
            "family",
            "rule",
            "path",
            "tool_use_id",
            "turn_id",
            "outcome",
            "duration_ms",
        }
        for row in decisions
    )


def test_explicit_block_mode_is_only_block_authority():
    response = prompt_submit.run(
        payload("skip the tests"), {"prompt_firewall_mode": "block"}
    )
    assert response["decision"] == "block"
    assert response["reason"].startswith("Agent discipline firewall blocked rules:")
    assert "skip_tests" in response["reason"]
    assert "skip the tests" not in response["reason"]


@pytest.mark.parametrize(
    "mode", [None, "enforce", "BLOCK", True, 1, {}, HostileString("block")]
)
def test_absent_invalid_or_hostile_mode_stays_inject(mode: object):
    cfg = {} if mode is None else {"prompt_firewall_mode": mode}
    response = prompt_submit.run(payload("skip the tests"), cfg)
    assert response.get("decision") is None
    assert "skip_tests" in context(response)


@pytest.mark.parametrize("project_mode", [None, "block", "inject", "BLOCK", True])
@pytest.mark.parametrize(
    ("caller_mode", "caller_present", "caller_blocks"),
    [
        (None, False, False),
        (None, True, False),
        ("block", True, True),
        ("inject", True, False),
        ("BLOCK", True, False),
        (True, True, False),
        (HostileString("block"), True, False),
    ],
)
def test_project_and_caller_mode_precedence_matrix(
    tmp_path: Path,
    project_mode: object,
    caller_mode: object,
    caller_present: bool,
    caller_blocks: bool,
):
    project = tmp_path / "project"
    project.mkdir()
    if project_mode is not None:
        (tmp_path / ".agent-discipline.json").write_text(
            json.dumps({"prompt_firewall_mode": project_mode}), encoding="utf-8"
        )
    config = {"prompt_firewall_mode": caller_mode} if caller_present else {}
    response = prompt_submit.run(payload("skip tests", cwd=str(project)), config)
    expected_block = caller_blocks or (not caller_present and project_mode == "block")
    assert (response.get("decision") == "block") is expected_block


def test_scanner_families_inject_and_respect_off_state():
    assert "english/ai_tell" in context(
        prompt_submit.run(payload("Please delve into this."))
    )
    assert (
        prompt_submit.run(
            payload("Please delve into this."), {"gates": {"english": "off"}}
        )
        == {}
    )
    observed = prompt_submit.run(
        payload("Please delve into this."), {"gates": {"english": "observe"}}
    )
    assert "english/ai_tell" in context(observed)


def test_enforced_scanner_family_cannot_invert_default_to_block():
    response = prompt_submit.run(
        payload("Please delve into this."), {"gates": {"english": "enforce"}}
    )
    assert response.get("decision") is None
    assert "english/ai_tell" in context(response)


def test_explicit_mode_can_block_scanner_finding():
    response = prompt_submit.run(
        payload("Please delve into this."),
        {"prompt_firewall_mode": "block", "gates": {"english": "observe"}},
    )
    assert response["decision"] == "block"
    assert "english/ai_tell" in response["reason"]


def test_scanner_findings_become_static_rule_reminders(monkeypatch: pytest.MonkeyPatch):
    secret = "private-token-123"
    monkeypatch.setattr(
        prompt_submit,
        "scan_all",
        lambda *_args, **_kwargs: [
            {
                "family": "secrets",
                "rule": "credential",
                "snippet": secret,
                "action": secret,
            }
        ],
    )
    monkeypatch.setattr(
        prompt_submit, "gate_state", lambda *_args, **_kwargs: "enforce"
    )
    response = prompt_submit.run(payload(secret))
    assert "secrets/credential" in context(response)
    assert secret not in context(response)


def test_project_config_can_explicitly_select_block(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / ".agent-discipline.json").write_text(
        json.dumps({"prompt_firewall_mode": "block"}), encoding="utf-8"
    )
    response = prompt_submit.run(payload("skip tests", cwd=str(project)))
    assert response["decision"] == "block"


def test_invalid_project_config_falls_back_to_inject(tmp_path: Path):
    (tmp_path / ".agent-discipline.json").write_text("{", encoding="utf-8")
    response = prompt_submit.run(payload("skip tests", cwd=str(tmp_path)))
    assert response.get("decision") is None


def test_invalid_scanner_config_cannot_erase_default_phrase_injection():
    response = prompt_submit.run(payload("skip tests"), {"exempt_paths": 1})
    assert response.get("decision") is None
    assert "skip_tests" in context(response)


def test_hostile_payload_config_keys_and_subclasses_are_harmless():
    assert prompt_submit.run(HostileDict(prompt="skip tests")) == {}
    hostile_key_payload = {CollidingKey(): "skip tests"}
    assert prompt_submit.run(hostile_key_payload) == {}
    assert prompt_submit.run(payload(HostileString("skip tests"))) == {}
    response = prompt_submit.run(
        payload("skip tests"), HostileDict(prompt_firewall_mode="block")
    )
    assert response.get("decision") is None


@pytest.mark.parametrize(
    ("session_id", "cwd"),
    [
        ("../escape", "\x00bad"),
        (HostileString("s1"), HostileString("/var/not-a-real-cwd")),
        ({}, []),
    ],
)
def test_invalid_session_and_cwd_do_not_affect_safe_response(
    session_id: object, cwd: object
):
    response = prompt_submit.run(payload("skip tests", session_id=session_id, cwd=cwd))
    assert response.get("decision") is None
    assert "skip_tests" in context(response)


def test_invalid_session_scans_but_never_writes_ledger(tmp_path: Path):
    response = prompt_submit.run(
        payload("skip tests", session_id="../escape"),
        {"ledger_root": str(tmp_path), "state_root": str(tmp_path / "state")},
    )
    assert "skip_tests" in context(response)
    assert not (tmp_path / "ledger.jsonl").exists()


@pytest.mark.parametrize(
    "missing", [{}, {"prompt": None}, {"user_prompt": HostileString("skip tests")}]
)
def test_missing_or_non_exact_prompt_is_noop(missing: dict):
    assert prompt_submit.run(missing) == {}


def test_huge_and_control_prompts_have_bounded_static_output():
    huge = "x" * (prompt_submit.MAX_PROMPT_CHARS + 1) + " skip the tests"
    assert prompt_submit.run(payload(huge)) == {}
    response = prompt_submit.run(payload("skip\x00 the tests; just comment it out"))
    assert len(json.dumps(response)) <= prompt_submit.MAX_RESPONSE_CHARS
    assert "comment_out_code" in context(response)


def test_exact_prompt_bound_handles_many_suppressed_matches():
    unit = "Do not skip tests. "
    repeats = prompt_submit.MAX_PROMPT_CHARS // len(unit)
    text = unit * repeats
    text += "x" * (prompt_submit.MAX_PROMPT_CHARS - len(text))
    assert len(text) == prompt_submit.MAX_PROMPT_CHARS
    assert (
        prompt_submit.run(
            payload(text),
            {"english": False, "punctuation": False, "clean_code": False},
        )
        == {}
    )


def test_ledger_contains_no_prompt_material_or_fingerprints(tmp_path: Path):
    secret = "skip the tests private-token-123"
    prompt_submit.run(
        payload(secret, session_id="s1"),
        {"ledger_root": str(tmp_path), "state_root": str(tmp_path / "state")},
    )
    ledger = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert secret not in ledger
    assert "private-token-123" not in ledger
    assert "snippet" not in ledger
    assert "hash" not in ledger
    assert "count" not in ledger
    assert "length" not in ledger


def test_valid_session_always_emits_one_heartbeat_including_clean(tmp_path: Path):
    cfg = {
        "ledger_root": str(tmp_path),
        "state_root": str(tmp_path / "state"),
        "english": False,
        "punctuation": False,
    }
    assert prompt_submit.run(payload("ordinary request", session_id="s1"), cfg) == {}
    rows = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["event"] == "observed"
    assert rows[0]["hook"] == "prompt_submit"


def test_scanner_exception_never_discloses_exception_or_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    marker = "PRIVATE-" + "SCANNER-" + "MARKER"

    def fail_scan(*_args, **_kwargs):
        raise RuntimeError(marker)

    monkeypatch.setattr(prompt_submit, "scan_all", fail_scan)
    response = prompt_submit.run(
        payload(f"skip tests {marker}", session_id="s1"),
        {"ledger_root": str(tmp_path), "state_root": str(tmp_path / "state")},
    )
    captured = capsys.readouterr()
    assert marker not in captured.err
    assert marker not in json.dumps(response)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert marker not in path.read_text(encoding="utf-8")


def test_ledger_and_state_failures_never_change_decision(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        prompt_submit.reporting, "append_row", mock.Mock(side_effect=OSError("disk"))
    )
    response = prompt_submit.run(
        payload("skip tests", session_id="s1"),
        {"state_root": "/unusable", "ledger_root": "/unusable"},
    )
    assert response.get("decision") is None
    assert "skip_tests" in context(response)


@pytest.mark.parametrize("invoke_gate", [False, True])
def test_reporting_failure_evaluates_once_and_preserves_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invoke_gate: bool,
):
    marker = "PRIVATE-REPORTING-MARKER"
    evaluate = mock.Mock(wraps=prompt_submit._evaluate)

    def fail_reporting(*, gate, **_kwargs):
        if invoke_gate:
            gate("turn-1")
        raise RuntimeError(marker)

    monkeypatch.setattr(prompt_submit, "_evaluate", evaluate)
    monkeypatch.setattr(prompt_submit.reporting, "run_with_ledger", fail_reporting)
    response = prompt_submit.run(
        payload(f"skip tests {marker}", session_id="s1"),
        {"ledger_root": str(tmp_path), "state_root": str(tmp_path / "state")},
    )
    captured = capsys.readouterr()
    assert evaluate.call_count == 1
    assert "skip_tests" in context(response)
    assert captured.err == "agent-discipline-watcher: prompt reporting failed\n"
    assert marker not in captured.err
    assert marker not in json.dumps(response)


def test_concurrent_valid_invocations_each_emit_one_heartbeat(tmp_path: Path):
    cfg = {
        "ledger_root": str(tmp_path),
        "state_root": str(tmp_path / "state"),
        "english": False,
        "punctuation": False,
    }

    def invoke(index: int) -> dict:
        return prompt_submit.run(payload("ordinary", session_id=f"s{index}"), cfg)

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert list(executor.map(invoke, range(32))) == [{}] * 32
    rows = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 32
    assert all(row["event"] == "observed" for row in rows)


def test_public_run_never_echoes_prompt_and_injection_is_capped():
    secret = "skip tests PRIVATE-MARKER"
    encoded = json.dumps(prompt_submit.run(payload(secret)))
    assert secret not in encoded
    assert "PRIVATE-MARKER" not in encoded
    assert len(encoded) <= prompt_submit.MAX_RESPONSE_CHARS


def test_ruleset_and_timeout_contract_are_versioned_and_nonblocking():
    assert prompt_submit.PROMPT_RULESET_VERSION == 1
    assert prompt_submit.EVENT_TIMEOUT_SECONDS == 30
    assert tuple(rule.rule_id for rule in prompt_submit.PROMPT_RULES) == (
        "skip_tests",
        "comment_out_code",
    )
    source = inspect.getsource(prompt_submit)
    assert "sleep(" not in source
    assert "requests" not in source
    assert "urlopen" not in source


def test_production_hook_passes_its_own_clean_code_scanner():
    source = Path(prompt_submit.__file__).read_text(encoding="utf-8")
    findings = scan_all(
        prompt_submit.__file__, source, {"punctuation": False, "english": False}
    )
    assert findings == []
