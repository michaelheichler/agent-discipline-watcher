"""Inject-first discipline firewall for UserPromptSubmit."""

from __future__ import annotations

import operator
import re
import sys
import time
import unicodedata
from contextlib import suppress
from typing import NamedTuple, cast

from lib import payloads, reporting, session_state
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
DATA_BOUNDARY_FINDING = ("data_boundary", "at_file_reference")
DATA_BOUNDARY_REASON = (
    "Data boundary blocked a file-reference token. Use the Read tool explicitly."
)


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
    r"(?<!\w)\"(?:\\.|[^\"\\\n])*\"|"
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
_AT_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_AT_SEGMENT = _AT_ALNUM | frozenset("_+~.-")
_AT_BOUNDARY_EXCLUDED = _AT_ALNUM | frozenset("_@./+~-")
_AT_TERMINATORS = frozenset(" \t\n\r\v\f,;:!?()[]{}")
_MIN_FENCE_WIDTH = 3
_MAX_FENCE_INDENT = 3
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


def _caller_mentions(config: object, key: str) -> bool:
    if not isinstance(config, dict):
        return False
    with suppress(Exception):
        for candidate in dict.keys(cast("dict[object, object]", config)):
            if operator.is_(type(candidate), str) and candidate == key:
                return True
    return False


def _resolved_config(config: dict[str, object], cwd: str) -> dict[str, object]:
    try:
        return effective_config(config, cwd or None)
    except (OSError, ValueError, TypeError, RuntimeError):
        return effective_config(config)


def _prompt(payload: object) -> str:
    text = payloads.prompt(payload)
    return text if len(text) <= MAX_PROMPT_CHARS else ""


def _cwd(payload: object) -> str:
    return _exact_text(payloads.cwd(payload), _MAX_CONFIG_TEXT)


def _session_id(payload: object) -> str:
    session_id = payloads.session_id(payload)
    return session_id if _SESSION_RE.fullmatch(session_id) else ""


def _mask_quoted(text: str) -> str:
    return _QUOTED_RE.sub(lambda match: " " * len(match.group(0)), text)


def _fence_body(line: str) -> str:
    indent = len(line) - len(line.lstrip(" "))
    return line[indent:] if indent <= _MAX_FENCE_INDENT else ""


def _fence_opener_width(line: str) -> int:
    body = _fence_body(line)
    width = len(body) - len(body.lstrip("`"))
    if width < _MIN_FENCE_WIDTH:
        return 0
    return width if "`" not in body[width:] else 0


def _is_fence_closer(line: str, width: int) -> bool:
    body = _fence_body(line)
    backticks = len(body) - len(body.lstrip("`"))
    return backticks >= width and not body[backticks:].strip(" \t\r\n")


def _mask_fenced(text: str) -> str:
    if "```" not in text:
        return text
    lines = text.splitlines(keepends=True)
    offsets = [0] * len(lines)
    for index in range(1, len(lines)):
        offsets[index] = offsets[index - 1] + len(lines[index - 1])
    masked = list(text)
    index = 0
    while index < len(lines):
        width = _fence_opener_width(lines[index])
        if not width:
            index += 1
            continue
        start = offsets[index]
        end = start + len(lines[index])
        index += 1
        while index < len(lines):
            end = offsets[index] + len(lines[index])
            closer = _is_fence_closer(lines[index], width)
            index += 1
            if closer:
                break
        for position in range(start, end):
            if masked[position] != "\n":
                masked[position] = " "
    return "".join(masked)


def _find_backtick_run(text: str, start: int, width: int) -> int:
    index = start
    while index < len(text):
        if text[index] != "`":
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] == "`":
            end += 1
        if end - index == width:
            return index
        index = end
    return -1


def _mask_code_width(text: str, width: int) -> str:
    if "`" * width not in text:
        return text
    masked = list(text)
    start = _find_backtick_run(text, 0, width)
    while start != -1:
        close = _find_backtick_run(text, start + width, width)
        if close == -1:
            break
        for position in range(start, close + width):
            if masked[position] != "\n":
                masked[position] = " "
        start = _find_backtick_run(text, close + width, width)
    return "".join(masked)


def _mask_inline_code(text: str) -> str:
    return _mask_code_width(_mask_code_width(text, 2), 1)


def _mask_examples(text: str) -> str:
    return _mask_quoted(_mask_inline_code(_mask_fenced(text)))


def _file_token_end(text: str, at: int) -> int:
    end = at + 1
    has_alnum = False
    segment_open = False
    for index in range(at + 1, len(text) + 1):
        char = text[index] if index < len(text) else ""
        if char in _AT_SEGMENT:
            has_alnum = has_alnum or char in _AT_ALNUM
            segment_open = True
            end = index + 1
        elif char == "/" and segment_open:
            segment_open = False
        else:
            break
    if end == at + 1 or not has_alnum:
        return -1
    return end if end == len(text) or _is_token_terminator(text[end]) else -1


def _is_token_terminator(char: str) -> bool:
    return char in _AT_TERMINATORS or char.isspace() or char == "`"


def _is_token_boundary(char: str) -> bool:
    return (
        char in _AT_BOUNDARY_EXCLUDED
        or char.isalnum()
        or unicodedata.category(char).startswith("M")
    )


def _has_file_token(text: str) -> bool:
    at = text.find("@")
    while at != -1:
        if (at == 0 or not _is_token_boundary(text[at - 1])) and (
            _file_token_end(text, at) != -1
        ):
            return True
        at = text.find("@", at + 1)
    return False


def _is_explanatory(text: str, start: int) -> bool:
    prefix = text[max(0, start - _MAX_PHRASE_CONTEXT) : start]
    chain = _NEGATION_CHAIN_RE.search(prefix)
    negated = bool(
        chain and len(_NEGATION_OPERATOR_RE.findall(chain.group(0))) % 2 == 1
    )
    return negated or bool(_EXPLANATORY_RE.search(prefix))


def _phrase_findings(text: str) -> dict[tuple[str, str], str]:
    scan_text = _mask_examples(text)
    matches: dict[tuple[str, str], str] = {}
    for rule in PROMPT_RULES:
        if any(
            not _is_explanatory(scan_text, match.start())
            for match in rule.pattern.finditer(scan_text)
        ):
            matches[(FIREWALL_FAMILY, rule.rule_id)] = rule.reminder
    return matches


def _data_boundary_enabled(cfg: dict[str, object]) -> bool:
    boundary = cfg.get("data_boundary")
    if not operator.is_(type(boundary), dict):
        return False
    fields = payloads.exact_string_dict(boundary)
    return operator.is_(fields.get("enabled"), True)


def _data_boundary_findings(
    text: str, cfg: dict[str, object]
) -> dict[tuple[str, str], str]:
    if not _data_boundary_enabled(cfg) or not _has_file_token(_mask_examples(text)):
        return {}
    return {DATA_BOUNDARY_FINDING: "Use the Read tool explicitly."}


def _scanner_findings(text: str, cfg: dict[str, object]) -> dict[tuple[str, str], str]:
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
    try:
        state = gate_state(family, cfg)
    except (AttributeError, TypeError, ValueError):
        return "enforce"
    return state if state in ("off", "observe", "enforce") else "enforce"


def _findings(text: str, cfg: dict[str, object]) -> dict[tuple[str, str], str]:
    combined = _phrase_findings(text)
    for key, value in _data_boundary_findings(text, cfg).items():
        combined.setdefault(key, value)
    for key, value in _scanner_findings(text, cfg).items():
        combined.setdefault(key, value)
    return dict(sorted(combined.items()))


def _mode(cfg: dict[str, object], selection: ModeSelection) -> str:
    value = selection.value if selection.caller_supplied else cfg.get(FIREWALL_MODE_KEY)
    return "block" if operator.is_(type(value), str) and value == "block" else "inject"


def _record(
    findings: dict[tuple[str, str], str],
    mode: str,
    session: SessionContext,
    duration_ms: int,
    cfg: dict[str, object],
) -> None:
    root = _config_root(cfg, "ledger_root")
    for family, rule in findings:
        outcome = "block" if (family, rule) == DATA_BOUNDARY_FINDING else mode
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
                outcome=outcome,
                duration_ms=duration_ms,
                turn_id=session.turn_id,
                root=root,
            )
            recorded = True
        if not recorded:
            sys.stderr.write("agent-discipline-watcher: prompt ledger append failed\n")


def _message(findings: dict[tuple[str, str], str]) -> str:
    rows = [
        f"- {family}/{rule}: {reminder}"
        for (family, rule), reminder in findings.items()
    ]
    return (
        f"Agent discipline reminder (prompt rules v{PROMPT_RULESET_VERSION}):\n"
        + "\n".join(rows)
    )[:MAX_RESPONSE_CHARS]


def _config_root(cfg: dict[str, object], key: str) -> str | None:
    return _exact_text(cfg.get(key), _MAX_CONFIG_TEXT) or None


def _advance_turn(session_id: str, cfg: dict[str, object]) -> None:
    """Advance here because a submitted prompt starts the ledger turn."""
    try:
        session_state.advance_turn(session_id, _config_root(cfg, "state_root"))
    except Exception:  # noqa: BLE001
        sys.stderr.write("agent-discipline-watcher: turn advance failed\n")


def _evaluate(
    text: str,
    cfg: dict[str, object],
    selection: ModeSelection,
    session: SessionContext,
) -> dict:
    if not text:
        return {}
    started = time.monotonic()
    findings = _findings(text, cfg)
    duration_ms = int((time.monotonic() - started) * 1000)
    if not findings:
        return {}
    boundary_block = DATA_BOUNDARY_FINDING in findings
    mode = _mode(cfg, selection)
    if session.session_id:
        _record(findings, mode, session, duration_ms, cfg)
    if boundary_block:
        return {"decision": "block", "reason": DATA_BOUNDARY_REASON}
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
        boundary_supplied = _caller_mentions(config, "data_boundary")
        safe_config = _safe_config(config)
        cfg = _resolved_config(safe_config, _cwd(payload))
        if boundary_supplied and "data_boundary" not in safe_config:
            cfg["data_boundary"] = False

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
        _advance_turn(session_id, cfg)
        try:
            return reporting.run_with_ledger(
                hook="prompt_submit",
                payload={"session_id": session_id},
                gate=gate,
                ledger_root=_config_root(cfg, "ledger_root"),
                state_root=_config_root(cfg, "state_root"),
            )
        except Exception:  # noqa: BLE001
            sys.stderr.write("agent-discipline-watcher: prompt reporting failed\n")
            return gate("")
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, re.error):
        sys.stderr.write("agent-discipline-watcher: prompt hook failed\n")
        return response


if __name__ == "__main__":
    write_payload(run(read_payload()))
