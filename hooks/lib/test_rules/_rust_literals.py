"""Read Rust tests as text, because hooks ship no Rust parser."""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from . import Hit, Unit

LOOP = "assert_in_loop"
NAME = "hardcoded_name_presence"
SOURCE = "hardcoded_literal_in_source"
_MASK_RE = re.compile(
    r'(?P<string>b?r(?P<hashes>#*)"[\s\S]*?"(?P=hashes)|b?"(?:\\[\s\S]|[^"\\])*")'
    r"|//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^\\'\n])'|'[A-Za-z_]\w*"
)
_BRACKET_RE = re.compile(r"[()\[\]{}]")
_LOOP_RE = re.compile(r"\b(?:for|while|loop)\b")
_MACRO_RE = re.compile(r"\bassert(?:_eq|_ne)?!\s*\(")
_LET_RE = re.compile(r"\blet\s+(?:mut\s+)?(?P<name>\w+)\s*(?::[^=;]+)?=\s*(?P<value>[^;]+);")
_LEAD_RE = re.compile(r"!?\s*[&*]*\s*(?P<name>\w+)")
_STATIC_RE = re.compile(r"[&*]*(?:\w+::)*_?[A-Z][A-Z0-9_]+")
_LITERAL_RE = re.compile(r'&?(?:b?"[^"]*"|-?\d[\d_]*(?:\.\d+)?(?:[a-z]\w*)?)')
_LOOKUP_RE = re.compile(
    r'!?\s*(?:\w+::)*_?[A-Z][A-Z0-9_]+\s*\.\s*(?:contains_key|contains|get)\s*\(\s*&?\s*b?"[^"]*"\s*\)'
    r"(?:\s*\.\s*is_(?:some|none)\s*\(\s*\))?"
)
_TEXT_CHECK_RE = re.compile(
    r'!?\s*(?P<subject>.+?)\s*\.\s*(?:contains|starts_with|ends_with)\s*\(\s*&?\s*b?"[^"]*"\s*\)'
)
_ANCHOR_RE = re.compile(r'"|\benv!|\bfile!')
_TEMP_RE = re.compile(r"tmp|temp|\.path\s*\(", re.IGNORECASE)


def _mask(body: str) -> str:
    """Blank strings but keep quotes, because a literal must show."""
    def replace(found: re.Match) -> str:
        chunk = re.sub(r"[^\n]", " ", found.group(0))
        return '"' + chunk[1:-1] + '"' if found.group("string") else chunk
    return _MASK_RE.sub(replace, body)


def _bracket_pairs(code: str) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for found in _BRACKET_RE.finditer(code):
        if found.group() in "([{":
            stack.append(found.start())
            continue
        if stack:
            pairs[stack.pop()] = found.start()
    return pairs


def _arguments(code: str, start: int, end: int) -> list[str]:
    parts: list[str] = []
    depth, begin = 0, start
    for index in range(start, end):
        depth += (code[index] in "([{") - (code[index] in ")]}")
        if code[index] == "," and depth == 0:
            parts.append(code[begin:index].strip())
            begin = index + 1
    parts.append(code[begin:end].strip())
    return [part for part in parts if part]


class _Macro(NamedTuple):
    position: int
    name: str
    arguments: list[str]


def _macros(code: str, pairs: dict[int, int]) -> Iterator[_Macro]:
    for found in _MACRO_RE.finditer(code):
        closing = pairs.get(found.end() - 1)
        if closing is not None:
            name = found.group().split("!")[0]
            yield _Macro(found.start(), name, _arguments(code, found.end(), closing))


def _loop_positions(code: str, pairs: dict[int, int]) -> Iterator[int]:
    """Report the outer loop once, because its asserts cover inner loops."""
    covered = -1
    for found in _LOOP_RE.finditer(code):
        opening = code.find("{", found.end())
        if found.start() < covered or opening not in pairs:
            continue
        covered = pairs[opening]
        first = _MACRO_RE.search(code, opening, covered)
        if first is not None:
            yield first.start()


def _reads_source(value: str) -> bool:
    if "include_str!" in value:
        return True
    return "read_to_string" in value and bool(_ANCHOR_RE.search(value)) and not _TEMP_RE.search(value)


def _sources(code: str) -> frozenset[str]:
    names: set[str] = set()
    for found in _LET_RE.finditer(code):
        lead = _LEAD_RE.match(found.group("value"))
        if _reads_source(found.group("value")) or (lead is not None and lead.group("name") in names):
            names.add(found.group("name"))
    return frozenset(names)


def _derived(expression: str, sources: frozenset[str]) -> bool:
    lead = _LEAD_RE.match(expression)
    return "include_str!" in expression or (lead is not None and lead.group("name") in sources)


def _either(arguments: list[str], fixed) -> bool:
    if len(arguments) < 2:
        return False
    left, right = arguments[:2]
    literal = _LITERAL_RE.fullmatch
    return bool((literal(left) and fixed(right)) or (literal(right) and fixed(left)))


def _macro_rule(macro: _Macro, sources: frozenset[str]) -> str | None:
    arguments = macro.arguments
    if macro.name == "assert":
        text_check = _TEXT_CHECK_RE.fullmatch(arguments[0]) if arguments else None
        if text_check is not None and _derived(text_check.group("subject"), sources):
            return SOURCE
        return NAME if arguments and _LOOKUP_RE.fullmatch(arguments[0]) else None
    if _either(arguments, lambda side: _derived(side, sources)):
        return SOURCE
    return NAME if _either(arguments, _STATIC_RE.fullmatch) else None


def rust_hits(unit: Unit) -> list[Hit]:
    """Mask strings first, because a quoted brace fakes a block."""
    code = _mask(unit.body)
    pairs = _bracket_pairs(code)
    sources = _sources(code)
    found = {(LOOP, position) for position in _loop_positions(code, pairs)}
    rules = ((_macro_rule(macro, sources), macro.position) for macro in _macros(code, pairs))
    found |= {(rule, position) for rule, position in rules if rule is not None}
    lines = unit.body.splitlines()
    rows = {(unit.body.count("\n", 0, position), rule) for rule, position in found}
    return [Hit(rule, unit.start + offset, lines[offset]) for offset, rule in sorted(rows)]
