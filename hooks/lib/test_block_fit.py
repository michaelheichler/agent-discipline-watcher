import json
from functools import partial
from pathlib import Path

from lib import hookio, host, principle_kb, reporting, session_state
from lib.finding_output import Explainer

REPORT = "/reports/full.json"
RULES = ("rule_a", "rule_b", "rule_c", "rule_d", "rule_e")
WIDE_ACTION = "Ersetze " + "ä" * 300 + "."


def _marker(rule: str) -> str:
    return f"MARK{rule.upper()}"


def _lookup(entry: str) -> principle_kb.Row:
    words = " ".join(["word"] * 75)
    return principle_kb.Row("deviq", entry, "Topic", f"{_marker(entry)} {words} end.")


def _explainer(claim) -> Explainer:
    return Explainer(_lookup, claim, {rule: rule for rule in RULES})


def _session_explainer(state_root: Path) -> Explainer:
    return _explainer(partial(session_state.claim_explained, "s1", root=state_root))


def _findings(action: str, rules: tuple[str, ...] = RULES) -> list[dict]:
    return [
        {"path": f"f{index}.py", "line": index + 1, "family": "code", "rule": rule, "action": action}
        for index, rule in enumerate(rules)
    ]


def _block(findings: list[dict], explainer: Explainer | None = None) -> str:
    return reporting.compact_block(findings, {}, explainer=explainer, report_path=REPORT)[0]


def _explained(text: str) -> list[str]:
    return [rule for rule in RULES if _marker(rule) in text]


def _sent_rows(text: str) -> int:
    return sum(f"f{index}.py:" in text for index in range(len(RULES)))


def test_a_wide_block_reaches_the_agent_with_its_report_path_last(monkeypatch, capsys) -> None:
    monkeypatch.delenv(host.CODEX_ENV, raising=False)
    block = _block(_findings(WIDE_ACTION))

    hookio.write_payload(hookio.claude_feedback_response({"decision": "block", "reason": block}, "PostToolUse"))

    sent = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert sent.splitlines()[-1].endswith(REPORT)


def test_the_report_line_counts_exactly_the_rows_left_out() -> None:
    block = _block(_findings(WIDE_ACTION))

    assert block.splitlines()[-1].split()[0] == str(len(RULES) - _sent_rows(block))


def test_a_wide_block_fits_one_hook_message_whole() -> None:
    block = _block(_findings(WIDE_ACTION))

    assert hookio.fits_once(block)


def test_every_principle_reaches_the_agent_once_when_the_first_block_overflows(tmp_path: Path) -> None:
    explainer = _session_explainer(tmp_path)
    first = _block(_findings(WIDE_ACTION), explainer)

    second = _block(_findings("Fix it."), explainer)

    assert sorted(_explained(first) + _explained(second)) == sorted(RULES)


def test_a_refused_claim_leaves_only_the_granted_principle_in_the_block() -> None:
    explainer = _explainer(lambda _rules: frozenset({"rule_a"}))

    block = _block(_findings("Fix it.", ("rule_a", "rule_b")), explainer)

    assert _explained(block) == ["rule_a"]
