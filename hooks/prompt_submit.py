from __future__ import annotations

import operator
import re
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import NamedTuple, cast

from lib import payloads, pending_advice, reporting, session_state, turn_adapter
from lib.config import SURFACE_PROSE, effective_hook_config, resolve_outcome
from lib.embedding_session import lease_root_for, open_turn
from lib.findings import Outcome
from lib.hookio import read_payload, write_payload
from lib.merge_state import mark_session_start
from lib.prompt_text import has_file_token, mask_examples
from lib.scanner import scan_all, scannable_text

PROMPT_RULESET_VERSION = 1
EVENT_TIMEOUT_SECONDS = 30
MAX_PROMPT_CHARS = 1_000_000
MAX_RESPONSE_CHARS = 4096
PROMPT_PATH = "user_prompt.md"
PROMPT_EVENT = "UserPromptSubmit"
FIREWALL_FAMILY = "prompt_firewall"
FIREWALL_MODE_KEY = "prompt_firewall_mode"
STYLE_NOTED_KEY = "prompt_style_noted"
class RuleKey(NamedTuple):
    family: str
    rule: str


DATA_BOUNDARY_FINDING = RuleKey("data_boundary", "at_file_reference")
DATA_BOUNDARY_REASON = (
    "Data boundary blocked a file-reference token. Use the Read tool explicitly."
)


class PromptRule(NamedTuple):
    rule_id: str
    pattern: re.Pattern[str]
    reminder: str


Scanner = Callable[[str, str, dict], list]
Ledger = Callable[..., dict]
StyleHits = frozenset[RuleKey]
Findings = dict[RuleKey, str]


class ModeSelection(NamedTuple):
    caller_supplied: bool
    value: object


class SessionContext(NamedTuple):
    session_id: str
    turn_id: str


@dataclass(frozen=True, slots=True)
class _PromptEvaluation:
    text: str
    config: dict[str, object]
    selection: ModeSelection
    session: SessionContext
    scan: Scanner = scan_all


PROMPT_RULES = (
    PromptRule(
        "skip_tests",
        re.compile(r"\bskip(?:ping)?\s+(?:the\s+)?tests?\b", re.IGNORECASE),
        "Keep required tests and verification. Fix failures instead of bypassing them.",
    ),
    PromptRule(
        "comment_out_code",
        re.compile(r"\bjust\s+comment\s+it\s+out\b", re.IGNORECASE),
        "Do not hide behavior in commented-out code. Make the smallest correct change.",
    ),
)

_NEGATION_OPERATOR = (
    r"(?:do\s+not|don['\u2019]t|never|avoid|refuse\s+to|must\s+not|"
    r"should\s+not|shouldn['\u2019]t)"
)
_NEGATION_CHAIN_RE = re.compile(rf"(?:\b{_NEGATION_OPERATOR}\s+)+$", re.IGNORECASE)
_NEGATION_OPERATOR_RE = re.compile(rf"\b{_NEGATION_OPERATOR}\b", re.IGNORECASE)
_EXPLANATORY_RE = re.compile(
    r"\b(?:phrase|wording|example)\b[^,;:.!?\n]*$", re.IGNORECASE
)
_SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z", re.ASCII)
_MAX_CONFIG_DEPTH = 5
_MAX_CONFIG_ITEMS = 256
_MAX_CONFIG_TEXT = 4096
_MAX_PHRASE_CONTEXT = 256
_MIN_CONTROL_CODEPOINT = 32
_DELETE_CODEPOINT = 127


def _exact_text(value: object, maximum: int) -> str:
    if not operator.is_(type(value), str):
        return ""
    text = cast(str, value)
    if not text or len(text) > maximum:
        return ""
    if any(
        ord(character) < _MIN_CONTROL_CODEPOINT or ord(character) == _DELETE_CODEPOINT
        for character in text
    ):
        return ""
    return text


def _safe_value(value: object, depth: int = 0) -> object | None:
    if depth > _MAX_CONFIG_DEPTH:
        return None
    if operator.is_(type(value), str):
        text = cast(str, value)
        return text if len(text) <= _MAX_CONFIG_TEXT else None
    if operator.is_(type(value), bool) or operator.is_(type(value), int):
        return value
    if operator.is_(type(value), list):
        return _safe_sequence(cast(list[object], value), depth)
    if operator.is_(type(value), dict):
        return _safe_mapping(payloads.exact_string_dict(value), depth)
    return None


def _safe_sequence(source: list[object], depth: int) -> list[object] | None:
    if len(source) > _MAX_CONFIG_ITEMS:
        return None
    copied = [_safe_value(item, depth + 1) for item in source]
    return copied if all(item is not None for item in copied) else None


def _safe_mapping(source: dict[str, object], depth: int) -> dict[str, object] | None:
    if len(source) > _MAX_CONFIG_ITEMS:
        return None
    result: dict[str, object] = {}
    for key, item in source.items():
        safe_item = _safe_value(item, depth + 1)
        if safe_item is not None:
            result[key] = safe_item
    return result


def _safe_config(config: object) -> dict[str, object]:
    copied = _safe_value(config)
    return cast(dict[str, object], copied) if operator.is_(type(copied), dict) else {}


def _resolved_config(config: dict[str, object], cwd: str) -> dict[str, object]:
    return effective_hook_config(config, cwd or None)


def _prompt(payload: object) -> str:
    text = payloads.prompt(payload)
    return text if len(text) <= MAX_PROMPT_CHARS else ""


def _cwd(payload: object) -> str:
    return _exact_text(payloads.cwd(payload), _MAX_CONFIG_TEXT)


def _session_id(payload: object) -> str:
    session_id = payloads.session_id(payload)
    return session_id if _SESSION_RE.fullmatch(session_id) else ""


def _is_explanatory(text: str, start: int) -> bool:
    prefix = text[max(0, start - _MAX_PHRASE_CONTEXT) : start]
    chain = _NEGATION_CHAIN_RE.search(prefix)
    negated = bool(
        chain and len(_NEGATION_OPERATOR_RE.findall(chain.group(0))) % 2 == 1
    )
    return negated or bool(_EXPLANATORY_RE.search(prefix))


def _phrase_findings(text: str) -> Findings:
    scan_text = mask_examples(text)
    matches: Findings = {}
    for rule in PROMPT_RULES:
        if any(
            not _is_explanatory(scan_text, match.start())
            for match in rule.pattern.finditer(scan_text)
        ):
            matches[RuleKey(FIREWALL_FAMILY, rule.rule_id)] = rule.reminder
    return matches


def _data_boundary_enabled(cfg: dict[str, object]) -> bool:
    boundary = cfg.get("data_boundary")
    if not operator.is_(type(boundary), dict):
        return False
    fields = payloads.exact_string_dict(boundary)
    return operator.is_(fields.get("enabled"), True)


def _data_boundary_findings(
    text: str, cfg: dict[str, object]
) -> Findings:
    if not _data_boundary_enabled(cfg) or not has_file_token(mask_examples(text)):
        return {}
    return {DATA_BOUNDARY_FINDING: "Use the Read tool explicitly."}


def _scanned_rules(text: str, cfg: dict[str, object], scan: Scanner) -> list[dict[str, object]]:
    raw_findings: list[dict[str, object]] | None = None
    with suppress(Exception):
        if scannable_text(text, cfg) is None:
            return []
        raw_findings = scan(PROMPT_PATH, text, cfg)
    if raw_findings is None:
        sys.stderr.write("agent-discipline-watcher: prompt scan failed\n")
        return []
    return raw_findings


def _style_hits(text: str, cfg: dict[str, object], scan: Scanner) -> StyleHits:
    hits: set[RuleKey] = set()
    for raw_finding in _scanned_rules(text, cfg, scan):
        finding = payloads.exact_string_dict(raw_finding)
        family = _exact_text(finding.get("family"), 128)
        rule = _exact_text(finding.get("rule"), 128)
        if family and rule and _enforced_on_prose(family, rule, cfg):
            hits.add(RuleKey(family, rule))
    return frozenset(hits)


def _enforced_on_prose(family: str, rule: str, cfg: dict[str, object]) -> bool:
    """Only an enforced rule is worth a note, because off and observe rules never ask the agent for anything."""
    finding = {"family": family, "rule": rule, "surface": SURFACE_PROSE}
    try:
        return resolve_outcome(finding, cfg) is Outcome.BLOCK
    except (AttributeError, TypeError, ValueError):
        return True


def _unnoted(hits: StyleHits, session: SessionContext, cfg: dict[str, object]) -> StyleHits:
    """Claimed under the state lock, because one note per rule per session is enough to steer the agent."""
    if not hits or not session.session_id:
        return hits
    claimed: set[str] = set()

    def mutate(state: dict) -> dict:
        stored = state.get(STYLE_NOTED_KEY)
        known = {name for name in stored if isinstance(name, str)} if isinstance(stored, list) else set()
        claimed.update({_style_name(hit) for hit in hits} - known)
        return {**state, STYLE_NOTED_KEY: sorted(known | claimed)}

    try:
        session_state.update_state(session.session_id, mutate, _config_root(cfg, "state_root"))
    except (OSError, ValueError, TypeError):
        return hits
    return frozenset(hit for hit in hits if _style_name(hit) in claimed)


def _style_name(hit: RuleKey) -> str:
    return f"{hit.family}/{hit.rule}"


def _findings(text: str, cfg: dict[str, object]) -> Findings:
    combined = _phrase_findings(text)
    for key, value in _data_boundary_findings(text, cfg).items():
        combined.setdefault(key, value)
    return dict(sorted(combined.items()))


def _mode(cfg: dict[str, object], selection: ModeSelection) -> str:
    value = selection.value if selection.caller_supplied else cfg.get(FIREWALL_MODE_KEY)
    return "block" if operator.is_(type(value), str) and value == "block" else "inject"


def _outcomes(
    findings: Findings, styles: StyleHits, mode: str,
) -> list[tuple[RuleKey, str]]:
    rows = [(key, "block" if key == DATA_BOUNDARY_FINDING else mode) for key in findings]
    rows.extend((key, "inject") for key in styles)
    return sorted(rows)


def _record(
    outcomes: list[tuple[RuleKey, str]], evaluation: _PromptEvaluation, duration_ms: int,
) -> None:
    session = evaluation.session
    root = _config_root(evaluation.config, "ledger_root")
    for (family, rule), outcome in outcomes:
        recorded = False
        with suppress(Exception):
            reporting.record_decision(
                session_id=session.session_id, hook="prompt_submit", event=PROMPT_EVENT,
                family=family, rule=rule, path=PROMPT_PATH, tool_use_id="", outcome=outcome,
                duration_ms=duration_ms, turn_id=session.turn_id, root=root,
            )
            recorded = True
        if not recorded:
            sys.stderr.write("agent-discipline-watcher: prompt ledger append failed\n")


def _style_rows(styles: StyleHits) -> list[str]:
    by_family: dict[str, list[str]] = {}
    for family, rule in sorted(styles):
        by_family.setdefault(family, []).append(rule)
    return [
        f"- The user prompt uses {family} patterns ({', '.join(rules)}). "
        "Do not copy that style into your output."
        for family, rules in by_family.items()
    ]


def _message(findings: Findings, styles: StyleHits) -> str:
    rows = [
        f"- {family}/{rule}: {reminder}"
        for (family, rule), reminder in findings.items()
    ]
    rows.extend(_style_rows(styles))
    return (
        f"Agent discipline reminder (prompt rules v{PROMPT_RULESET_VERSION}):\n"
        + "\n".join(rows)
    )[:MAX_RESPONSE_CHARS]


def _config_root(cfg: dict[str, object], key: str) -> str | None:
    return _exact_text(cfg.get(key), _MAX_CONFIG_TEXT) or None


def _firewall_block_response(findings: Findings) -> dict:
    names = ", ".join(f"{family}/{rule}" for family, rule in findings)
    return {
        "decision": "block",
        "reason": ("Agent discipline firewall blocked rules: " + names)[:MAX_RESPONSE_CHARS],
    }


def _evaluation_inputs(
    payload: object, config: object,
) -> tuple[str, str, dict[str, object], ModeSelection]:
    text = _prompt(payload)
    session_id = _session_id(payload)
    caller_fields = payloads.exact_string_dict(config)
    selection = ModeSelection(
        FIREWALL_MODE_KEY in caller_fields,
        caller_fields.get(FIREWALL_MODE_KEY),
    )
    boundary_supplied = "data_boundary" in caller_fields
    safe_config = _safe_config(config)
    cfg = _resolved_config(safe_config, _cwd(payload))
    if boundary_supplied and "data_boundary" not in safe_config:
        cfg["data_boundary"] = False
    return text, session_id, cfg, selection


def _run_with_prompt_ledger(
    session_id: str, cfg: dict[str, object], gate: Callable[[str], dict], ledger: Ledger,
) -> dict:
    try:
        return ledger(
            hook="prompt_submit",
            payload={"session_id": session_id},
            gate=gate,
            ledger_root=_config_root(cfg, "ledger_root"),
            state_root=_config_root(cfg, "state_root"),
        )
    except Exception:  # noqa: BLE001
        sys.stderr.write("agent-discipline-watcher: prompt reporting failed\n")
        return gate("")


def _evaluate(evaluation: _PromptEvaluation) -> dict:
    if not evaluation.text:
        return {}
    started = time.monotonic()
    findings = _findings(evaluation.text, evaluation.config)
    hits = _style_hits(evaluation.text, evaluation.config, evaluation.scan)
    duration_ms = int((time.monotonic() - started) * 1000)
    mode = _mode(evaluation.config, evaluation.selection)
    blocked = DATA_BOUNDARY_FINDING in findings or (mode == "block" and bool(findings))
    styles = frozenset() if blocked else _unnoted(hits, evaluation.session, evaluation.config)
    if not findings and not styles:
        return {}
    if evaluation.session.session_id:
        _record(_outcomes(findings, styles, mode), evaluation, duration_ms)
    if DATA_BOUNDARY_FINDING in findings:
        return {"decision": "block", "reason": DATA_BOUNDARY_REASON}
    if blocked:
        return _firewall_block_response(findings)
    return {
        "hookSpecificOutput": {
            "hookEventName": PROMPT_EVENT,
            "additionalContext": _message(findings, styles),
        }
    }


def _with_advice(response: dict, session_id: str, cfg: dict[str, object]) -> dict:
    """Held past a blocked prompt, because the agent never answers a prompt the hook blocked."""
    if response.get("decision") == "block":
        return response
    known = response.get("hookSpecificOutput", {}).get("additionalContext", "")
    budget = MAX_RESPONSE_CHARS - len(known) - (len(pending_advice.SEPARATOR) if known else 0)
    advice = pending_advice.take(session_id, _config_root(cfg, "state_root"), budget)
    if not advice:
        return response
    message = pending_advice.SEPARATOR.join(part for part in (known, advice) if part)
    return {**response, "hookSpecificOutput": {"hookEventName": PROMPT_EVENT, "additionalContext": message}}


def run(payload: object, config: object = None, *, scan: Scanner = scan_all, ledger: Ledger = reporting.run_with_ledger) -> dict:
    response: dict[str, object] = {}
    try:
        text, session_id, cfg, selection = _evaluation_inputs(payload, config)
        evaluated = False

        def gate(turn_id: str) -> dict:
            nonlocal evaluated, response
            if evaluated:
                return response
            evaluated = True
            response = _evaluate(
                _PromptEvaluation(text, cfg, selection, SessionContext(session_id, turn_id), scan)
            )
            return response

        if not session_id:
            return gate("")
        with suppress(OSError, ValueError, TypeError):
            mark_session_start(session_id, _config_root(cfg, "state_root"))
        if not turn_adapter.prepare_turn(session_id, cast(dict, cfg)):
            open_turn(session_id, lease_root_for(cast(dict, cfg)))
        return _with_advice(_run_with_prompt_ledger(session_id, cfg, gate, ledger), session_id, cfg)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, re.error):
        sys.stderr.write("agent-discipline-watcher: prompt hook failed\n")
        return response


if __name__ == "__main__":
    write_payload(run(read_payload()))
