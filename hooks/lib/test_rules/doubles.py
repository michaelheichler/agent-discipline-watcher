"""Stay STATIC, because the mocked type's owner file is not read."""
from __future__ import annotations

import ast
import copy
import functools
import re

try:
    from . import Hit, Rule, RuleSet, module_scopes, module_tree
    from ..test_units import PYTHON, RUST, Unit
except ImportError:
    from test_rules import Hit, Rule, RuleSet, module_scopes, module_tree
    from test_units import PYTHON, RUST, Unit

_INTERFACE_BASES = frozenset({"Protocol", "ABC"})
_MOCK_FACTORIES = frozenset({"Mock", "MagicMock", "AsyncMock", "create_autospec"})
_ARGUMENT_CHECKS = frozenset({"assert_called_with", "assert_called_once_with", "assert_any_call", "assert_has_calls"})
_RUST_STRUCT_RE = re.compile(r"\bstruct\s+(?P<name>[A-Z]\w*)")
_RUST_TRAIT_RE = re.compile(r"\btrait\s+(?P<name>[A-Z]\w*)")
_RUST_MOCK_NEW_RE = re.compile(r"\bMock(?P<name>[A-Z]\w*)::new\s*\(")
_RUST_EXPECT_STMT_RE = re.compile(r"[^;]*\.expect_\w+[^;]*;", re.DOTALL)

MOCKING_CONCRETE_CLASSES = Rule(
    "mocking_concrete_classes",
    "Mock built directly from a concrete class",
    "Mock the interface or protocol instead of the concrete type.",
)
INCOMPLETE_MOCK_CALL_VERIFICATION = Rule(
    "incomplete_mock_call_verification",
    "Mock call check skips the arguments",
    "Check the exact arguments, such as with assert_called_once_with.",
)


def _line_at(unit: Unit, index: int) -> int:
    """Count newlines, because a unit keeps its own file offset only."""
    return unit.start + unit.body.count("\n", 0, index)


@functools.lru_cache(maxsize=4)
def _python_class_defs(text: str) -> dict[str, ast.ClassDef]:
    """Read the whole file, because a spec target may sit outside the unit."""
    tree = module_tree(text)
    if tree is None:
        return {}
    interface_names = set(_INTERFACE_BASES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"typing", "typing_extensions", "abc"}:
            interface_names.update(alias.asname or alias.name for alias in node.names
                                   if alias.name in _INTERFACE_BASES)
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            and not _is_interfaceish(node, interface_names)}


def _is_interfaceish(node: ast.ClassDef, interface_names: set[str]) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else None
        if name in interface_names:
            return True
    return False


def _concrete_target(name: str, classes: dict[str, ast.ClassDef]) -> bool:
    node = classes.get(name.rsplit(".", 1)[-1])
    return node is not None


def _call_name(node: ast.Call) -> str:
    return ast.unparse(node.func)


def _spec_target(node: ast.Call) -> str | None:
    name = _call_name(node)
    tail = name.rsplit(".", 1)[-1]
    if tail in _MOCK_FACTORIES:
        target = next((kw.value for kw in node.keywords if kw.arg in {"spec", "spec_set"}), None)
        if target is None and node.args:
            target = node.args[0]
        return ast.unparse(target) if isinstance(target, (ast.Name, ast.Attribute)) else None
    if name.endswith("patch.object") and node.args:
        return ast.unparse(node.args[0])
    if tail == "patch" and node.args and isinstance(node.args[0], ast.Constant):
        value = node.args[0].value
        return value if isinstance(value, str) else None
    return None


def _ast_hit(unit: Unit, node: ast.AST, rule: str) -> Hit:
    return Hit(rule, node.lineno, unit.body.splitlines()[node.lineno - unit.start])


def _spec_matches(unit: Unit, classes: dict[str, ast.ClassDef], node: ast.Call) -> list[Hit]:
    target = _spec_target(node)
    if target and _concrete_target(target, classes):
        return [_ast_hit(unit, node, MOCKING_CONCRETE_CLASSES.name)]
    return []


def _mock_spec_hits(unit: Unit, classes: dict[str, ast.ClassDef], tree: ast.AST) -> list[Hit]:
    return [hit for node in ast.walk(tree) if isinstance(node, ast.Call)
            for hit in _spec_matches(unit, classes, node)]


def _mock_roots(tree: ast.AST) -> set[str]:
    roots = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and _call_name(node.value).rsplit(".", 1)[-1] in _MOCK_FACTORIES):
            roots.update(target.id for target in node.targets if isinstance(target, ast.Name))
        if isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
            if "patch" in _call_name(node.context_expr).split(".") and isinstance(node.optional_vars, ast.Name):
                roots.add(node.optional_vars.id)
    return roots


def _argument_comparisons(tree: ast.AST) -> set[str]:
    verified = set()
    for assertion in ast.walk(tree):
        if not isinstance(assertion, ast.Assert) or not isinstance(assertion.test, ast.Compare):
            continue
        compare = assertion.test
        pairs = zip([compare.left, *compare.comparators], compare.comparators, compare.ops)
        for left, right, operation in pairs:
            if not isinstance(operation, ast.Eq):
                continue
            for attribute, expected in ((left, right), (right, left)):
                if (isinstance(attribute, ast.Attribute) and attribute.attr in {"call_args", "call_args_list"}
                        and isinstance(expected, (ast.Tuple, ast.List, ast.Call))):
                    verified.add(ast.unparse(attribute.value))
    return verified


def _count_hits(unit: Unit, tree: ast.AST) -> list[Hit]:
    roots = _mock_roots(tree)
    exact = {ast.unparse(node.func.value) for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in _ARGUMENT_CHECKS}
    exact.update(_argument_comparisons(tree))
    hits = []
    for assertion in ast.walk(tree):
        if not isinstance(assertion, ast.Assert) or not isinstance(assertion.test, ast.Compare):
            continue
        for node in ast.walk(assertion.test):
            if not isinstance(node, ast.Attribute) or node.attr != "call_count":
                continue
            receiver = ast.unparse(node.value)
            if receiver.split(".", 1)[0] in roots and receiver not in exact:
                hits.append(_ast_hit(unit, node, INCOMPLETE_MOCK_CALL_VERIFICATION.name))
    return hits


def _bare_assert_hits(unit: Unit, tree: ast.AST) -> list[Hit]:
    return [_ast_hit(unit, node, INCOMPLETE_MOCK_CALL_VERIFICATION.name)
            for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr in {"assert_called", "assert_called_once"}
            and not node.args and not node.keywords] + _count_hits(unit, tree)


def _rust_type_defs(text: str) -> tuple[set[str], set[str]]:
    return (
        {found.group("name") for found in _RUST_STRUCT_RE.finditer(text)},
        {found.group("name") for found in _RUST_TRAIT_RE.finditer(text)},
    )


def _mock_new_hits(unit: Unit, structs: set[str], traits: set[str]) -> list[Hit]:
    matches = [found for found in _RUST_MOCK_NEW_RE.finditer(unit.body)
               if found.group("name") in structs and found.group("name") not in traits]
    return [Hit(MOCKING_CONCRETE_CLASSES.name, _line_at(unit, found.start()), found.group(0)) for found in matches]


def _is_incomplete_expect(statement: str) -> bool:
    return (".times(" in statement or ".once(" in statement) and ".with(" not in statement


def _expect_chain_hits(unit: Unit) -> list[Hit]:
    matches = [found for found in _RUST_EXPECT_STMT_RE.finditer(unit.body) if _is_incomplete_expect(found.group(0))]
    return [
        Hit(INCOMPLETE_MOCK_CALL_VERIFICATION.name, _line_at(unit, found.start()), found.group(0).strip())
        for found in matches
    ]


def _python_hits(unit: Unit, text: str) -> list[Hit]:
    tree = module_tree(text)
    scope = module_scopes(tree).get((unit.start, unit.end)) if tree else None
    if scope is None:
        return []
    # Because unit bodies exclude outer decorators, leave the cached node intact.
    scope = copy.copy(scope)
    scope.decorator_list = []
    classes = _python_class_defs(text)
    return _mock_spec_hits(unit, classes, scope) + _bare_assert_hits(unit, scope)


def _rust_hits(unit: Unit, text: str) -> list[Hit]:
    structs, traits = _rust_type_defs(text)
    return _mock_new_hits(unit, structs, traits) + _expect_chain_hits(unit)


def check(unit: Unit, text: str) -> list[Hit]:
    """Split by language, because Python and Rust name their doubles differently."""
    if unit.language == PYTHON:
        return _python_hits(unit, text)
    if unit.language == RUST:
        return _rust_hits(unit, text)
    return []


RULE_SET = RuleSet(
    rules=(MOCKING_CONCRETE_CLASSES, INCOMPLETE_MOCK_CALL_VERIFICATION),
    check=check,
)
