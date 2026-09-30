"""Flag test-structure smells, because a branching or reused test hides its scenario."""
from __future__ import annotations

import ast
import functools
import re

from . import Hit, Rule, RuleSet, Unit

IF_NAME = "if_statements_in_tests"
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_MATCH_TYPES = getattr(ast, "Match", None)


@functools.lru_cache(maxsize=8)
def _module(text: str) -> ast.Module | None:
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _test_node(unit: Unit, text: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    tree = _module(text)
    for node in ast.walk(tree) if tree else ():
        if isinstance(node, _FUNCTIONS) and node.name == unit.name and node.lineno == unit.start:
            return node
    return None


def _has_assert(statements: list[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Assert) for stmt in statements for node in ast.walk(stmt))


def _branches_on_assert(node: ast.If) -> bool:
    """Skip a guard clause, because it never opens a second branch."""
    return bool(node.orelse) and _has_assert(node.body) and _has_assert(node.orelse)


def _match_branches_on_assert(node: ast.AST) -> bool:
    """Need two case bodies, because one case alone is not a branch."""
    return sum(1 for case in node.cases if _has_assert(case.body)) >= 2


def _if_hits(test: ast.AST) -> list[int]:
    nodes = list(ast.walk(test))
    hits = [node for node in nodes if isinstance(node, ast.If) and _branches_on_assert(node)]
    if _MATCH_TYPES:
        matches = (node for node in nodes if isinstance(node, _MATCH_TYPES))
        hits += [node for node in matches if _match_branches_on_assert(node)]
    return [node.lineno for node in hits]


_RUST_MASK_RE = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/')
_RUST_ASSERT_RE = re.compile(r"\bassert(?:_eq|_ne)?!")
_RUST_IF_RE = re.compile(r"\bif\b[^{}]*\{")
_RUST_ELSE_RE = re.compile(r"\s*else\s*(?:if\b[^{}]*)?\{")


def _rust_mask(body: str) -> str:
    """Blank strings and comments, because a quoted brace fakes a block."""
    return _RUST_MASK_RE.sub(lambda found: re.sub(r"[^\n]", " ", found.group(0)), body)


def _rust_brace_pairs(code: str) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for index, character in enumerate(code):
        if character == "{":
            stack.append(index)
            continue
        if character == "}" and stack:
            pairs[stack.pop()] = index
    return pairs


def _rust_else_open(code: str, if_close: int) -> int | None:
    found = _RUST_ELSE_RE.match(code, if_close + 1)
    return code.index("{", if_close + 1, found.end()) if found else None


def _rust_if_hit(found: re.Match, code: str, pairs: dict[int, int]) -> int | None:
    """Report the if line, because that is where the branch choice starts."""
    if_open = found.end() - 1
    if_close = pairs.get(if_open)
    else_open = _rust_else_open(code, if_close) if if_close is not None else None
    else_close = pairs.get(else_open) if else_open is not None else None
    if else_close is None:
        return None
    if_body, else_body = code[if_open + 1:if_close], code[else_open + 1:else_close]
    if _RUST_ASSERT_RE.search(if_body) and _RUST_ASSERT_RE.search(else_body):
        return code.count("\n", 0, found.start())
    return None


def _rust_if_hits(unit: Unit) -> list[Hit]:
    code = _rust_mask(unit.body)
    pairs = _rust_brace_pairs(code)
    lines = unit.body.splitlines()
    matches = _RUST_IF_RE.finditer(code)
    offsets = (_rust_if_hit(found, code, pairs) for found in matches)
    found_offsets = [offset for offset in offsets if offset is not None]
    return [Hit(IF_NAME, unit.start + offset, lines[offset]) for offset in found_offsets]


def check(unit: Unit, text: str) -> list[Hit]:
    """Share one entry, because the registry calls check per test."""
    if unit.language == "rust":
        return _rust_if_hits(unit)
    test = _test_node(unit, text)
    if test is None:
        return []
    lines = text.splitlines()
    return [Hit(IF_NAME, line, lines[line - 1]) for line in sorted(set(_if_hits(test)))]


RULE_SET = RuleSet(
    rules=(
        Rule(IF_NAME, "Test branches between two different asserts",
             "Split the branches into their own test methods."),
    ),
    check=check,
)
