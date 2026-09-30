"""Stay STATIC, because the mocked type's owner file is not read."""
from __future__ import annotations

import ast
import re

try:
    from . import Hit, Rule, RuleSet, module_tree
    from ..test_units import PYTHON, RUST, Unit
except ImportError:
    from test_rules import Hit, Rule, RuleSet, module_tree
    from test_units import PYTHON, RUST, Unit

_INTERFACE_BASES = frozenset({"Protocol", "ABC"})
_MOCK_SPEC_RE = re.compile(r"\b(?:Mock|MagicMock)\(\s*spec(?:_set)?\s*=\s*(?P<name>[A-Za-z_][\w.]*)")
_PATCH_RE = re.compile(r"\bpatch\(\s*[\"'](?P<path>[\w.]+)[\"']")
_BARE_ASSERT_RE = re.compile(r"\.assert_called(?:_once)?\(\s*\)")
_PY_CLOCK_RE = re.compile(r"\b(?:time\.time|datetime\.(?:now|utcnow)|date\.today)\s*\(")
_PY_PATCH_CLOCK_RE = re.compile(
    r"patch\(\s*[\"'][\w.]*\b(?:time\.time|datetime\.now|datetime\.utcnow|date\.today)[\"']"
)
_RUST_STRUCT_RE = re.compile(r"\bstruct\s+(?P<name>[A-Z]\w*)")
_RUST_TRAIT_RE = re.compile(r"\btrait\s+(?P<name>[A-Z]\w*)")
_RUST_MOCK_NEW_RE = re.compile(r"\bMock(?P<name>[A-Z]\w*)::new\s*\(")
_RUST_EXPECT_STMT_RE = re.compile(r"[^;]*\.expect_\w+[^;]*;", re.DOTALL)
_RUST_CLOCK_RE = re.compile(r"\b(?:Instant|SystemTime|Utc)::now\s*\(")

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
TIME_AS_AMBIENT_CONTEXT = Rule(
    "time_as_ambient_context",
    "Test reads the real clock",
    "Pass a fixed time into the code instead of reading the system clock.",
)


def _line_at(unit: Unit, index: int) -> int:
    """Count newlines, because a unit keeps its own file offset only."""
    return unit.start + unit.body.count("\n", 0, index)


def _python_class_defs(text: str) -> dict[str, ast.ClassDef]:
    """Read the whole file, because a spec target may sit outside the unit."""
    tree = module_tree(text)
    if tree is None:
        return {}
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _is_interfaceish(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else None
        if name in _INTERFACE_BASES:
            return True
    return False


def _concrete_target(name: str, classes: dict[str, ast.ClassDef]) -> bool:
    node = classes.get(name.rsplit(".", 1)[-1])
    return node is not None and not _is_interfaceish(node)


_SPEC_TARGETS = (
    (_MOCK_SPEC_RE, "name"),
    (_PATCH_RE, "path"),
)


def _spec_matches(unit: Unit, classes: dict[str, ast.ClassDef], spec: tuple[re.Pattern, str]) -> list[Hit]:
    pattern, group = spec
    matches = [found for found in pattern.finditer(unit.body) if _concrete_target(found.group(group), classes)]
    return [Hit(MOCKING_CONCRETE_CLASSES.name, _line_at(unit, found.start()), found.group(0)) for found in matches]


def _mock_spec_hits(unit: Unit, classes: dict[str, ast.ClassDef]) -> list[Hit]:
    return [hit for spec in _SPEC_TARGETS for hit in _spec_matches(unit, classes, spec)]


def _bare_assert_hits(unit: Unit) -> list[Hit]:
    return [
        Hit(INCOMPLETE_MOCK_CALL_VERIFICATION.name, _line_at(unit, found.start()), found.group(0))
        for found in _BARE_ASSERT_RE.finditer(unit.body)
    ]


def _clock_hits_python(unit: Unit) -> list[Hit]:
    calls = [Hit(TIME_AS_AMBIENT_CONTEXT.name, _line_at(unit, found.start()), found.group(0))
             for found in _PY_CLOCK_RE.finditer(unit.body)]
    patches = [Hit(TIME_AS_AMBIENT_CONTEXT.name, _line_at(unit, found.start()), found.group(0))
               for found in _PY_PATCH_CLOCK_RE.finditer(unit.body)]
    return calls + patches


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


def _clock_hits_rust(unit: Unit) -> list[Hit]:
    return [
        Hit(TIME_AS_AMBIENT_CONTEXT.name, _line_at(unit, found.start()), found.group(0))
        for found in _RUST_CLOCK_RE.finditer(unit.body)
    ]


def _python_hits(unit: Unit, text: str) -> list[Hit]:
    classes = _python_class_defs(text)
    return _mock_spec_hits(unit, classes) + _bare_assert_hits(unit) + _clock_hits_python(unit)


def _rust_hits(unit: Unit, text: str) -> list[Hit]:
    structs, traits = _rust_type_defs(text)
    return _mock_new_hits(unit, structs, traits) + _expect_chain_hits(unit) + _clock_hits_rust(unit)


def check(unit: Unit, text: str) -> list[Hit]:
    """Split by language, because Python and Rust name their doubles differently."""
    if unit.language == PYTHON:
        return _python_hits(unit, text)
    if unit.language == RUST:
        return _rust_hits(unit, text)
    return []


RULE_SET = RuleSet(
    rules=(MOCKING_CONCRETE_CLASSES, INCOMPLETE_MOCK_CALL_VERIFICATION, TIME_AS_AMBIENT_CONTEXT),
    check=check,
)
