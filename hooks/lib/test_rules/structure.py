"""Flag test-structure smells, because a branching or reused test hides its scenario."""
from __future__ import annotations

import ast
import functools
import re

from . import Hit, Rule, RuleSet, Unit

IF_NAME = "if_statements_in_tests"
ACT_NAME = "multiple_act_sections_in_unit_test"
CTOR_NAME = "test_fixture_reuse_via_constructor"
_SUT = "sut"
_CONSTRUCTOR_NAMES = frozenset({"setUp", "__init__"})
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_MATCH_TYPES = getattr(ast, "Match", None)


def _second_act_index(acts: list[int], asserts: list[int]) -> int | None:
    """Need act, assert, act, assert in order, because one act is normal."""
    if len(acts) < 2:
        return None
    first_assert = next((index for index in asserts if index > acts[0]), None)
    if first_assert is None:
        return None
    second_act = next((index for index in acts if index > first_assert), None)
    if second_act is None:
        return None
    second_assert = next((index for index in asserts if index > second_act), None)
    return second_act if second_assert is not None else None


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


def _dotted_root(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_sut_call(stmt: ast.stmt) -> bool:
    value = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign)) else None
    return isinstance(value, ast.Call) and _dotted_root(value.func) == _SUT


def _second_act_line(test: ast.FunctionDef | ast.AsyncFunctionDef) -> int | None:
    """Read top-level statements only, because a with-block runs one act."""
    acts = [index for index, stmt in enumerate(test.body) if _is_sut_call(stmt)]
    asserts = [index for index, stmt in enumerate(test.body) if isinstance(stmt, ast.Assert)]
    second_act = _second_act_index(acts, asserts)
    return test.body[second_act].lineno if second_act is not None else None


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


_RUST_SUT_CALL_RE = re.compile(r"\bsut\s*\.\s*\w+\s*\(")


def _rust_act_hits(unit: Unit) -> list[Hit]:
    code = _rust_mask(unit.body)
    lines = code.splitlines()
    acts = [index for index, line in enumerate(lines) if _RUST_SUT_CALL_RE.search(line)]
    asserts = [index for index, line in enumerate(lines) if _RUST_ASSERT_RE.search(line)]
    second_act = _second_act_index(acts, asserts)
    if second_act is None:
        return []
    return [Hit(ACT_NAME, unit.start + second_act, unit.body.splitlines()[second_act])]


def _self_attr(node: ast.expr) -> str | None:
    """Match self.name, because a bare name is a local, not fixture state."""
    is_self_owned = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    return node.attr if is_self_owned and node.value.id == "self" else None


def _built_attrs(method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    built = set()
    assigns = (node for node in ast.walk(method) if isinstance(node, ast.Assign))
    for node in assigns:
        if isinstance(node.value, ast.Call):
            built |= {attr for target in node.targets if (attr := _self_attr(target))}
    return built

def _enclosing_class(tree: ast.Module, unit: Unit) -> ast.ClassDef | None:
    classes = (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    for node in classes:
        starts = (child.lineno for child in node.body if isinstance(child, _FUNCTIONS))
        if unit.start in starts:
            return node
    return None


def _constructor(cls: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    methods = (node for node in cls.body if isinstance(node, _FUNCTIONS))
    return next((node for node in methods if node.name in _CONSTRUCTOR_NAMES), None)


def _reused_line(test: ast.FunctionDef | ast.AsyncFunctionDef, built: set[str]) -> int | None:
    """Any call on the built attribute counts, because it exercises shared state."""
    calls = (node for node in ast.walk(test) if isinstance(node, ast.Call))
    owned = (node for node in calls if isinstance(node.func, ast.Attribute))
    hits = (node.lineno for node in owned if _self_attr(node.func.value) in built)
    return next(hits, None)


def _ctor_hit(unit: Unit, tree: ast.Module) -> int | None:
    cls = _enclosing_class(tree, unit)
    ctor = _constructor(cls) if cls is not None else None
    if ctor is None:
        return None
    built = _built_attrs(ctor)
    test = _test_node_in(cls, unit) if built else None
    return _reused_line(test, built) if test is not None else None


def _test_node_in(cls: ast.ClassDef, unit: Unit) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    methods = (node for node in cls.body if isinstance(node, _FUNCTIONS))
    return next((node for node in methods if node.lineno == unit.start), None)


def check(unit: Unit, text: str) -> list[Hit]:
    """Share one entry, because the registry calls check per test."""
    if unit.language == "rust":
        return _rust_if_hits(unit) + _rust_act_hits(unit)
    test = _test_node(unit, text)
    if test is None:
        return []
    lines = text.splitlines()
    hits = [Hit(IF_NAME, line, lines[line - 1]) for line in sorted(set(_if_hits(test)))]
    act_line = _second_act_line(test)
    if act_line is not None:
        hits.append(Hit(ACT_NAME, act_line, lines[act_line - 1]))
    ctor_line = _ctor_hit(unit, _module(text))
    if ctor_line is not None:
        hits.append(Hit(CTOR_NAME, ctor_line, lines[ctor_line - 1]))
    return hits


RULE_SET = RuleSet(
    rules=(
        Rule(IF_NAME, "Test branches between two different asserts",
             "Split the branches into their own test methods."),
        Rule(ACT_NAME, "Test calls the unit under test, asserts, then calls it and asserts again",
             "Split the second act and assert into their own test method."),
        Rule(CTOR_NAME, "Test calls an object that setUp or __init__ built for the whole class",
             "Move the setup into a factory method the test calls for itself."),
    ),
    check=check,
)
