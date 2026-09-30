"""Flag tests that pin literals, because they guard no behavior."""
from __future__ import annotations

import ast
import functools
import re
from collections.abc import Callable, Iterable, Iterator
from typing import NamedTuple

from . import Hit, Rule, RuleSet, Unit
from ._rust_literals import rust_hits

LOOP = "assert_in_loop"
NAME = "hardcoded_name_presence"
SOURCE = "hardcoded_literal_in_source"
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_SCOPES = (*_FUNCTIONS, ast.Lambda, ast.ClassDef)
_UPPER_RE = re.compile(r"_?[A-Z][A-Z0-9_]+")
_TEMP_RE = re.compile(r"tmp|temp", re.IGNORECASE)
_SUBTEST_CALLS = frozenset({"subTest", "subtests.test"})
_VIEW_CALLS = frozenset({"set", "list", "sorted", "tuple", "frozenset", "len", "dict"})
_VIEW_METHODS = frozenset({"keys", "values", "items", "get"})
_READ_METHODS = frozenset({"read_text", "read_bytes"})
_OPEN_READS = frozenset({"read", "readlines"})
_OPEN_CALLS = frozenset({"open", "io.open"})
_SOURCE_CALLS = frozenset({"inspect.getsource", "getsource"})
_PARSERS = frozenset({
    "json.loads", "tomllib.loads", "yaml.safe_load", "len", "set", "list", "sorted", "str",
    "tuple", "frozenset", "re.findall", "re.search", "re.match", "re.fullmatch",
})
_PAIR_ASSERTS = frozenset({
    "assertEqual", "assertNotEqual", "assertListEqual", "assertDictEqual",
    "assertSetEqual", "assertCountEqual", "assertTupleEqual",
})
_IN_ASSERTS = frozenset({"assertIn", "assertNotIn"})
_REGEX_ASSERTS = frozenset({"assertRegex", "assertNotRegex"})
_REGEX_CALLS = frozenset({"search", "match", "fullmatch", "findall"})
_COMPARE_KINDS = {
    ast.In: "in", ast.NotIn: "in", ast.Eq: "eq", ast.NotEq: "eq", ast.Is: "eq", ast.IsNot: "eq",
}
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


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


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _dotted(node.value) + "." + node.attr
    return ""


def _call_name(node: ast.AST) -> str:
    return _dotted(node.func) if isinstance(node, ast.Call) else ""


def _is_assertion(node: ast.AST) -> bool:
    name = _call_name(node)
    return isinstance(node, ast.Assert) or name.split(".")[-1].startswith("assert") or name == "pytest.raises"


def _opens_subtest(node: ast.AST) -> bool:
    return isinstance(node, (ast.With, ast.AsyncWith)) and any(
        _call_name(item.context_expr).removeprefix("self.") in _SUBTEST_CALLS for item in node.items
    )


def _loop_assertions(node: ast.AST) -> Iterator[ast.AST]:
    """Stop at subTest, because each case there reports alone."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES) or _opens_subtest(child):
            continue
        if _is_assertion(child):
            yield child
        yield from _loop_assertions(child)


def _outer_loops(node: ast.AST) -> Iterator[ast.AST]:
    children = [child for child in ast.iter_child_nodes(node) if not isinstance(child, _SCOPES)]
    yield from (child for child in children if isinstance(child, _LOOPS))
    for child in children:
        if not isinstance(child, _LOOPS):
            yield from _outer_loops(child)


def _loop_hits(test: ast.AST) -> Iterator[tuple[str, int]]:
    for loop in _outer_loops(test):
        first = next(_loop_assertions(loop), None)
        if first is not None:
            yield LOOP, first.lineno


def _bound_names(test: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    params = {arg.arg for arg in ast.walk(test.args) if isinstance(arg, ast.arg)}
    stored = {node.id for node in ast.walk(test) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    return frozenset(params | stored)


def _literal(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes, int, float))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _literal(node.operand)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return bool(node.elts) and all(_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys) and all(_literal(item) for item in (*node.keys, *node.values))
    return False


def _static_root(node: ast.expr, bound: frozenset[str]) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id not in bound


def _static_call(node: ast.Call, bound: frozenset[str]) -> bool:
    if isinstance(node.func, ast.Attribute) and node.func.attr in _VIEW_METHODS:
        return all(map(_literal, node.args)) and _static(node.func.value, bound)
    return len(node.args) == 1 and _dotted(node.func) in _VIEW_CALLS and _static(node.args[0], bound)


def _static(node: ast.expr, bound: frozenset[str]) -> bool:
    """Trust only constants, because a call result is behavior."""
    if isinstance(node, (ast.Dict, ast.Set)):
        return True
    if isinstance(node, _COMPREHENSIONS):
        return all(_static(generator.iter, bound) for generator in node.generators)
    if isinstance(node, ast.Name):
        return node.id not in bound and bool(_UPPER_RE.fullmatch(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_UPPER_RE.fullmatch(node.attr) and _static_root(node, bound)) or _static(node.value, bound)
    if isinstance(node, ast.Subscript):
        return _literal(node.slice) and _static(node.value, bound)
    return isinstance(node, ast.Call) and _static_call(node, bound)


class _Scope(NamedTuple):
    params: frozenset[str]
    bound: frozenset[str]
    bindings: dict[str, ast.expr]


def _bindings(nodes: Iterable[ast.AST]) -> dict[str, ast.expr]:
    found: dict[str, ast.expr] = {}
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found.update({target.id: node.value for target in targets if isinstance(target, ast.Name)})
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            found[node.target.id] = node.iter
        if isinstance(node, (ast.With, ast.AsyncWith)):
            found.update({
                item.optional_vars.id: item.context_expr
                for item in node.items if isinstance(item.optional_vars, ast.Name)
            })
    return found


def _scope(test: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.Module) -> _Scope:
    params = frozenset(arg.arg for arg in ast.walk(test.args) if isinstance(arg, ast.arg))
    local = _bindings(sorted(ast.walk(test), key=lambda node: getattr(node, "lineno", 0)))
    return _Scope(params, _bound_names(test) - set(local), {**_bindings(tree.body), **local})


def _path_names_ok(node: ast.expr, scope: _Scope, depth: int) -> bool:
    for leaf in ast.walk(node):
        if isinstance(leaf, ast.Attribute) and _TEMP_RE.search(leaf.attr):
            return False
        if isinstance(leaf, ast.Name) and not _name_is_static_path(leaf.id, scope, depth):
            return False
    return True


def _name_is_static_path(name: str, scope: _Scope, depth: int) -> bool:
    if _TEMP_RE.search(name) or name in scope.params or name in scope.bound:
        return False
    return name not in scope.bindings or _static_path(scope.bindings[name], scope, depth + 1)


def _anchored(node: ast.expr, scope: _Scope, depth: int) -> bool:
    for leaf in ast.walk(node):
        if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
            return True
        if isinstance(leaf, ast.Name) and (leaf.id == "__file__" or _UPPER_RE.fullmatch(leaf.id)):
            return True
        if isinstance(leaf, ast.Attribute) and leaf.attr == "__file__":
            return True
        binding = scope.bindings.get(leaf.id) if isinstance(leaf, ast.Name) and depth < 4 else None
        if binding is not None and _anchored(binding, scope, depth + 1):
            return True
    return False


def _static_path(node: ast.expr, scope: _Scope, depth: int = 0) -> bool:
    """Skip temp paths, because a test may read its own output."""
    return depth < 4 and _path_names_ok(node, scope, depth) and _anchored(node, scope, depth)


def _opened(node: ast.expr, scope: _Scope) -> ast.expr | None:
    target = scope.bindings.get(node.id, node) if isinstance(node, ast.Name) else node
    return target.args[0] if _call_name(target) in _OPEN_CALLS and target.args else None


def _reads_source(node: ast.expr, scope: _Scope) -> bool:
    if _call_name(node) in _SOURCE_CALLS:
        return True
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr in _READ_METHODS:
        return _static_path(node.func.value, scope)
    path = _opened(node.func.value, scope) if node.func.attr in _OPEN_READS else None
    return path is not None and _static_path(path, scope)


def _derived(node: ast.expr, scope: _Scope, depth: int = 0) -> bool:
    """Stop at other calls, because they run the code under test."""
    if depth > 4:
        return False
    if isinstance(node, ast.Name):
        binding = scope.bindings.get(node.id)
        return binding is not None and _derived(binding, scope, depth + 1)
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        return _derived(node.value, scope, depth)
    return isinstance(node, ast.Call) and _derived_call(node, scope, depth)


def _derived_call(node: ast.Call, scope: _Scope, depth: int) -> bool:
    if _reads_source(node, scope):
        return True
    if _dotted(node.func) in _PARSERS:
        return any(_derived(arg, scope, depth) for arg in node.args)
    return isinstance(node.func, ast.Attribute) and _derived(node.func.value, scope, depth)


def _assert_pair(test: ast.expr) -> tuple[str, ast.expr, ast.expr] | None:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test = test.operand
    operator = type(test.ops[0]) if isinstance(test, ast.Compare) and len(test.ops) == 1 else None
    if operator in _COMPARE_KINDS:
        return _COMPARE_KINDS[operator], test.left, test.comparators[0]
    if _call_name(test).removeprefix("re.") in _REGEX_CALLS and len(test.args) >= 2:
        return "in", test.args[0], test.args[1]
    return None


def _call_pair(call: ast.Call) -> tuple[str, ast.expr, ast.expr] | None:
    method = _call_name(call).split(".")[-1]
    if len(call.args) < 2:
        return None
    if method in _IN_ASSERTS:
        return "in", call.args[0], call.args[1]
    if method in _REGEX_ASSERTS:
        return "in", call.args[1], call.args[0]
    return ("eq", call.args[0], call.args[1]) if method in _PAIR_ASSERTS else None


class _Pair(NamedTuple):
    line: int
    kind: str
    left: ast.expr
    right: ast.expr


def _pairs(test: ast.AST) -> Iterator[_Pair]:
    for node in ast.walk(test):
        pair = _assert_pair(node.test) if isinstance(node, ast.Assert) else None
        pair = pair or (_call_pair(node) if isinstance(node, ast.Call) else None)
        if pair is not None:
            yield _Pair(node.lineno, *pair)


def _pins(pair: _Pair, fixed: Callable[[ast.expr], bool]) -> bool:
    """Accept either order, because assertEqual has no convention."""
    if pair.kind == "in":
        return _literal(pair.left) and fixed(pair.right)
    return (_literal(pair.left) and fixed(pair.right)) or (_literal(pair.right) and fixed(pair.left))


def _pair_rule(pair: _Pair, scope: _Scope, bound: frozenset[str]) -> str | None:
    if _pins(pair, lambda node: _derived(node, scope)):
        return SOURCE
    return NAME if _pins(pair, lambda node: _static(node, bound)) else None


def _literal_hits(test: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.Module) -> Iterator[tuple[str, int]]:
    scope = _scope(test, tree)
    bound = _bound_names(test)
    rules = ((_pair_rule(pair, scope, bound), pair.line) for pair in _pairs(test))
    return ((rule, line) for rule, line in rules if rule is not None)


def check(unit: Unit, text: str) -> list[Hit]:
    """Share one entry, because the registry calls check per test."""
    if unit.language == "rust":
        return rust_hits(unit)
    test = _test_node(unit, text)
    if test is None:
        return []
    lines = text.splitlines()
    found = sorted({*_loop_hits(test), *_literal_hits(test, _module(text))}, key=lambda hit: (hit[1], hit[0]))
    return [Hit(rule, line, lines[line - 1]) for rule, line in found]


RULE_SET = RuleSet(
    rules=(
        Rule(LOOP, "Test asserts inside a loop, so the first failing case hides the rest",
             "Parameterize the cases or wrap each one in subTest."),
        Rule(NAME, "Test pins a hard-coded name or value in a static table",
             "Assert the behavior the name drives instead of its presence."),
        Rule(SOURCE, "Test asserts a literal in the text of a source or config file",
             "Test the behavior the text produces instead of the text."),
    ),
    check=check,
)
