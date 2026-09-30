"""Match private access, because a test should use the public seam."""
from __future__ import annotations

import re

try:
    from . import Hit, Rule, RuleSet
except ImportError:
    from lib.test_rules import Hit, Rule, RuleSet

METHODS_RULE = Rule(
    "exposing_private_methods_for_testing",
    "Calls a private method or patches a private name directly",
    "Call the public method that exercises this path instead.",
)
STATE_RULE = Rule(
    "exposing_private_state_for_testing",
    "Reads or writes a private attribute directly",
    "Assert on the public result the call already returns.",
)

# Skip these, because a namedtuple exposes them on purpose.
_NAMEDTUPLE_NAMES = frozenset({"_replace", "_asdict", "_make", "_fields", "_field_defaults"})

_PRIVATE_CALL = re.compile(
    r"\b(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>_[A-Za-z][A-Za-z0-9_]*)\s*\("
)
_PRIVATE_ATTR = re.compile(
    r"\b(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>_[A-Za-z][A-Za-z0-9_]*)\b(?!\s*\()"
)
_MONKEYPATCH = re.compile(
    r"\bmonkeypatch\.setattr\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*[\"'](?P<name>_[A-Za-z][A-Za-z0-9_]*)[\"']"
)
_STRING_LITERAL = re.compile(
    r"'''(?:\\.|[^\\])*?'''|\"\"\"(?:\\.|[^\\])*?\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"",
    re.DOTALL,
)


def _masked(body: str) -> str:
    """Blank string literals, because a dotted config key is not an attribute."""
    return _STRING_LITERAL.sub(lambda found: re.sub(r"[^\n]", " ", found.group(0)), body)


def _line_at(unit_start: int, body: str, index: int) -> int:
    """Add newline count, because a unit starts mid file."""
    return unit_start + body.count("\n", 0, index)


def _snippet_at(body: str, index: int) -> str:
    """Bound the line, because a hit shows one line."""
    line_start = body.rfind("\n", 0, index) + 1
    line_end = body.find("\n", index)
    return body[line_start:line_end] if line_end != -1 else body[line_start:]


def _own_private_calls(unit_start: int, scan_text: str, body: str):
    for found in _PRIVATE_CALL.finditer(scan_text):
        if found.group("owner") == "self" or found.group("name") in _NAMEDTUPLE_NAMES:
            continue
        yield Hit(METHODS_RULE.name, _line_at(unit_start, body, found.start()),
                  _snippet_at(body, found.start()))


def _own_monkeypatch_calls(unit_start: int, body: str):
    for found in _MONKEYPATCH.finditer(body):
        yield Hit(METHODS_RULE.name, _line_at(unit_start, body, found.start()),
                  _snippet_at(body, found.start()))


def _own_private_attrs(unit_start: int, scan_text: str, body: str):
    for found in _PRIVATE_ATTR.finditer(scan_text):
        if found.group("owner") == "self" or found.group("name") in _NAMEDTUPLE_NAMES:
            continue
        yield Hit(STATE_RULE.name, _line_at(unit_start, body, found.start()),
                  _snippet_at(body, found.start()))


def check(unit, _text: str) -> list[Hit]:
    """Scan Python only, because underscores carry no privacy rule in Rust."""
    if unit.language != "python":
        return []
    body = unit.body
    scan_text = _masked(body)
    return [
        *_own_private_calls(unit.start, scan_text, body),
        *_own_monkeypatch_calls(unit.start, body),
        *_own_private_attrs(unit.start, scan_text, body),
    ]


RULE_SET = RuleSet(rules=(METHODS_RULE, STATE_RULE), check=check)
