"""Inject-first discipline firewall for UserPromptSubmit."""

from __future__ import annotations

import operator
import re
import sys
import time
from contextlib import suppress
from typing import NamedTuple, cast

from lib import payloads, reporting
from lib.config import effective_config, gate_state
from lib.hookio import read_payload, write_payload
from lib.scanner import scan_all, scannable_text

PROMPT_RULESET_VERSION = 1
EVENT_TIMEOUT_SECONDS = 30
MAX_PROMPT_CHARS = 1_000_000
MAX_RESPONSE_CHARS = 4096
PROMPT_PATH = "user_prompt.md"
PROMPT_EVENT = "UserPromptSubmit"
FIREWALL_FAMILY = "prompt_firewall"
FIREWALL_MODE_KEY = "prompt_firewall_mode"


class PromptRule(NamedTuple):
    rule_id: str
    pattern: re.Pattern[str]
    reminder: str


class ModeSelection(NamedTuple):
    caller_supplied: bool
    value: object


class SessionContext(NamedTuple):
    session_id: str
    turn_id: str


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

_QUOTED_RE = re.compile(
    r"`[^`\n]*`|(?<!\w)\"(?:\\.|[^\"\\\n])*\"|"
    r"(?<!\w)'(?:\\.|[^'\\\n])*'|"
    r"(?<!\w)\u201c[^\u201d\n]*\u201d|(?<!\w)\u2018[^\u2019\n]*\u2019"
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
    """Return bounded control-free built-in text."""
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
    """Copy a bounded JSON-like config value without invoking subclass methods."""
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
    """Return a bounded recursive copy of an exact built-in list."""
    if len(source) > _MAX_CONFIG_ITEMS:
        return None
    copied = [_safe_value(item, depth + 1) for item in source]
    return copied if all(item is not None for item in copied) else None


def _safe_mapping(source: dict[str, object], depth: int) -> dict[str, object] | None:
    """Return a bounded recursive copy of an exact built-in mapping."""
    if len(source) > _MAX_CONFIG_ITEMS:
        return None
    result: dict[str, object] = {}
    for key, item in source.items():
        safe_item = _safe_value(item, depth + 1)
        if safe_item is not None:
            result[key] = safe_item
    return result


def _safe_config(config: object) -> dict[str, object]:
    """Return an inert built-in config projection."""
    copied = _safe_value(config)
    return cast(dict[str, object], copied) if operator.is_(type(copied), dict) else {}


def _resolved_config(config: dict[str, object], cwd: str) -> dict[str, object]:
    """Merge safe caller and project config, falling back when project I/O fails."""
    try:
        return effective_config(config, cwd or None)
    except (OSError, ValueError, TypeError, RuntimeError):
        return effective_config(config)


def _prompt(payload: object) -> str:
    """Project the exact prompt field and enforce the scan bound."""
    text = payloads.prompt(payload)
    return text if len(text) <= MAX_PROMPT_CHARS else ""


def _cwd(payload: object) -> str:
    """Project a path safe to pass to project-config resolution."""
    return _exact_text(payloads.cwd(payload), _MAX_CONFIG_TEXT)


def _session_id(payload: object) -> str:
    """Return a bounded session id safe for state and ledger helpers."""
    session_id = payloads.session_id(payload)
    return session_id if _SESSION_RE.fullmatch(session_id) else ""


def _mask_quoted(text: str) -> str:
    """Blank quoted examples while preserving match positions."""
    return _QUOTED_RE.sub(lambda match: " " * len(match.group(0)), text)


def _is_explanatory(text: str, start: int) -> bool:
    """Return whether the matched phrase is directly negated or labeled as an example."""
    prefix = text[max(0, start - _MAX_PHRASE_CONTEXT) : start]
    chain = _NEGATION_CHAIN_RE.search(prefix)
    negated = bool(
        chain and len(_NEGATION_OPERATOR_RE.findall(chain.group(0))) % 2 == 1
    )
    return negated or bool(_EXPLANATORY_RE.search(prefix))


def _phrase_findings(text: str) -> dict[tuple[str, str], str]:
    """Return reviewed rules found in unquoted, affirmative prompt text."""
    scan_text = _mask_quoted(text)
    matches: dict[tuple[str, str], str] = {}
    for rule in PROMPT_RULES:
        if any(
            not _is_explanatory(scan_text, match.start())
            for match in rule.pattern.finditer(scan_text)
        ):
            matches[(FIREWALL_FAMILY, rule.rule_id)] = rule.reminder
    return matches


def _scanner_findings(text: str, cfg: dict[str, object]) -> dict[tuple[str, str], str]:
    """Convert enabled scanner findings to static rule identifiers and reminders."""
    raw_findings: list[dict[str, object]] | None = None
    with suppress(Exception):
        if scannable_text(text, cfg) is None:
            return {}
        raw_findings = scan_all(PROMPT_PATH, text, cfg)
    if raw_findings is None:
        sys.stderr.write("agent-discipline-watcher: prompt scan failed\n")
        return {}
    findings: dict[tuple[str, str], str] = {}
    for raw_finding in raw_findings:
        finding = payloads.exact_string_dict(raw_finding)
        family = _exact_text(finding.get("family"), 128)
        rule = _exact_text(finding.get("rule"), 128)
        if not family or not rule or _family_state(family, cfg) == "off":
            continue
        findings[(family, rule)] = "Correct this discipline violation before complying."
    return dict(sorted(findings.items()))


def _family_state(family: str, cfg: dict[str, object]) -> str:
    """Resolve a scanner family safely; invalid state defaults to enabled injection."""
    try:
        state = gate_state(family, cfg)
    except (AttributeError, TypeError, ValueError):
        return "enforce"
    return state if state in ("off", "observe", "enforce") else "enforce"


def _findings(text: str, cfg: dict[str, object]) -> dict[tuple[str, str], str]:
    """Compose reviewed phrase and scanner findings in stable identifier order."""
    combined = _phrase_findings(text)
    for key, value in _scanner_findings(text, cfg).items():
        combined.setdefault(key, value)
    return dict(sorted(combined.items()))


def _mode(cfg: dict[str, object], selection: ModeSelection) -> str:
    """Resolve caller authority before project mode, defaulting every invalid value to inject."""
    value = selection.value if selection.caller_supplied else cfg.get(FIREWALL_MODE_KEY)
    return "block" if operator.is_(type(value), str) and value == "block" else "inject"


def _record(
    findings: dict[tuple[str, str], str],
    mode: str,
    session: SessionContext,
    duration_ms: int,
    cfg: dict[str, object],
) -> None:
    """Persist standard decision metadata without prompt-derived values."""
    root = _config_root(cfg, "ledger_root")
    for family, rule in findings:
        recorded = False
        with suppress(Exception):
            reporting.record_decision(
                session_id=session.session_id,
                hook="prompt_submit",
                event=PROMPT_EVENT,
                family=family,
                rule=rule,
                path=PROMPT_PATH,
                tool_use_id="",
                outcome=mode,
                duration_ms=duration_ms,
                turn_id=session.turn_id,
                root=root,
            )
            recorded = True
        if not recorded:
            sys.stderr.write("agent-discipline-watcher: prompt ledger append failed\n")


def _message(findings: dict[tuple[str, str], str]) -> str:
    """Build bounded guidance solely from static identifiers and reminders."""
    rows = [
        f"- {family}/{rule}: {reminder}"
        for (family, rule), reminder in findings.items()
    ]
    return (
        f"Agent discipline reminder (prompt rules v{PROMPT_RULESET_VERSION}):\n"
        + "\n".join(rows)
    )[:MAX_RESPONSE_CHARS]


def _config_root(cfg: dict[str, object], key: str) -> str | None:
    """Return a bounded exact root path or the helper default."""
    return _exact_text(cfg.get(key), _MAX_CONFIG_TEXT) or None


def _evaluate(
    text: str,
    cfg: dict[str, object],
    selection: ModeSelection,
    session: SessionContext,
) -> dict:
    """Scan one bounded prompt and record each static finding."""
    if not text:
        return {}
    started = time.monotonic()
    findings = _findings(text, cfg)
    duration_ms = int((time.monotonic() - started) * 1000)
    if not findings:
        return {}
    mode = _mode(cfg, selection)
    if session.session_id:
        _record(findings, mode, session, duration_ms, cfg)
    if mode == "block":
        names = ", ".join(f"{family}/{rule}" for family, rule in findings)
        return {
            "decision": "block",
            "reason": ("Agent discipline firewall blocked rules: " + names)[
                :MAX_RESPONSE_CHARS
            ],
        }
    return {
        "hookSpecificOutput": {
            "hookEventName": PROMPT_EVENT,
            "additionalContext": _message(findings),
        }
    }


def run(payload: object, config: object = None) -> dict:
    """Evaluate one prompt without persisting prompt-derived content."""
    response: dict[str, object] = {}
    try:
        text = _prompt(payload)
        session_id = _session_id(payload)
        caller_fields = payloads.exact_string_dict(config)
        selection = ModeSelection(
            FIREWALL_MODE_KEY in caller_fields,
            caller_fields.get(FIREWALL_MODE_KEY),
        )
        cfg = _resolved_config(_safe_config(config), _cwd(payload))

        evaluated = False

        def gate(turn_id: str) -> dict:
            nonlocal evaluated, response
            if evaluated:
                return response
            evaluated = True
            response = _evaluate(
                text,
                cfg,
                selection,
                SessionContext(session_id, turn_id),
            )
            return response

        if not session_id:
            return gate("")
        try:
            return reporting.run_with_ledger(
                hook="prompt_submit",
                payload={"session_id": session_id},
                gate=gate,
                ledger_root=_config_root(cfg, "ledger_root"),
                state_root=_config_root(cfg, "state_root"),
            )
        except Exception:
            sys.stderr.write("agent-discipline-watcher: prompt reporting failed\n")
            return gate("")
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, re.error):
        sys.stderr.write("agent-discipline-watcher: prompt hook failed\n")
        return response


if __name__ == "__main__":
    write_payload(run(read_payload()))
