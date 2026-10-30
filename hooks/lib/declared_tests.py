"""Tests recognized by what a file declares, because a name or a folder is wrong both ways."""
from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import PurePath

try:
    from .brace_functions import BRACE_LANGUAGE_EXTS
    from .test_units import rust_cfg_test_blocks
except ImportError:
    from brace_functions import BRACE_LANGUAGE_EXTS
    from test_units import rust_cfg_test_blocks

PYTHON_EXTS = frozenset({".py", ".pyi"})
PYTHON_FRAMEWORKS = frozenset({"pytest", "unittest", "hypothesis", "nose", "nose2", "testtools", "doctest", "behave", "pytest_bdd"})
PYTHON_CASE_BASES = frozenset({"TestCase", "IsolatedAsyncioTestCase"})
PYTEST_SETTINGS = frozenset({"pytestmark", "collect_ignore", "collect_ignore_glob", "__test__"})
BRANCHING = (ast.If, ast.Try, ast.With, ast.AsyncWith)
PYTHON_FALLBACK_RE = re.compile(r"^(?:import|from)\s+(?:pytest|unittest|hypothesis)\b|^\s*def test_\w*\(.*:\s*\n\s+assert\b", re.M)
JS_TEST_IMPORT_RE = (
    r"(?:\bfrom|\brequire\s*\(|^\s*import)\s*['\"](?:vitest|jest|@jest/globals|bun:test|node:test|mocha|chai|ava|tap|uvu"
    r"|@playwright/test|@testing-library/[\w-]+|supertest)(?:/[^'\"]*)?['\"]"
)
JS_TEST_CALL_RE = r"^\s*(?:describe|it|test|suite|context|bench)(?:(?:\.\w+)*\s*\(\s*['\"`]|(?:\.\w+)*\.each\b)"
RUST_TEST_RE = re.compile(r"#\[\s*(?:tokio\s*::\s*)?test\b")
GO_TEST = r'^import\s+(?:\w+\s+)?"testing"|^\s*(?:\w+\s+)?"testing"\s*$|^func\s+(?:Test|Benchmark|Fuzz|Example)(?![a-z])\w*\s*\('
RUBY_TEST = (
    r"^\s*require(?:_relative)?\s*\(?\s*['\"](?:rspec|minitest|test/unit|test_helper|spec_helper|rails_helper)\b"
    r"|\bRSpec\.describe\b|^\s*describe\s+\S.*\bdo\b|<\s*(?:Minitest::Test|Test::Unit::TestCase|ActiveSupport::TestCase)\b|^\s*def\s+test_"
)
JVM_TEST = (
    r"^\s*import\s+(?:static\s+)?(?:org\.junit|org\.testng|io\.kotest|kotlin\.test|org\.spockframework|org\.scalatest|munit)\b"
    r"|@(?:Test|ParameterizedTest|RepeatedTest|TestFactory)\b"
)
DOTNET_TEST = r"^\s*using\s+(?:Xunit|NUnit\.Framework|Microsoft\.VisualStudio\.TestTools)\b|\[\s*(?:Fact|Theory|Test|TestMethod|TestCase|TestFixture)\b"
PHP_TEST = r"PHPUnit\\Framework|\bextends\s+(?:\\?\w+\\)*TestCase\b|^\s*(?:it|test|describe)\s*\(\s*['\"]"
SWIFT_TEST = r"^\s*(?:@testable\s+)?import\s+(?:XCTest|Testing)\b|\bXCTestCase\b|^\s*@Test\b"
ELIXIR_TEST = r"\buse\s+ExUnit\.Case\b|^\s*test\s+\""
NATIVE_TEST = (
    r"^\s*#\s*include\s*[<\"](?:gtest/|gmock/|catch2/|catch\.hpp|doctest|boost/test/|CUnit/|check\.h|unity\.h|criterion/)"
    r"|^\s*(?:TEST|TEST_F|TEST_P|TYPED_TEST|TEST_CASE|SCENARIO)\s*\("
)
DART_TEST = r"^\s*import\s+['\"]package:(?:test|flutter_test|integration_test)/"
SHELL_TEST = r"^@test\s|^\s*(?:\.|source)\s+\S*shunit2\b"
LUA_TEST = r"^\s*(?:describe|it)\s*\(\s*['\"]"
SNAPSHOT_TEST = r"^exports\["
PATTERNS = {
    **dict.fromkeys(BRACE_LANGUAGE_EXTS, JS_TEST_IMPORT_RE + "|" + JS_TEST_CALL_RE),
    ".go": GO_TEST, ".rb": RUBY_TEST, ".php": PHP_TEST, ".swift": SWIFT_TEST, ".dart": DART_TEST,
    **dict.fromkeys((".java", ".kt", ".kts", ".scala", ".groovy"), JVM_TEST),
    ".cs": DOTNET_TEST, ".ex": ELIXIR_TEST, ".exs": ELIXIR_TEST,
    **dict.fromkeys((".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"), NATIVE_TEST),
    **dict.fromkeys((".bats", ".sh", ".bash"), SHELL_TEST),
    ".lua": LUA_TEST, ".snap": SNAPSHOT_TEST,
}
COMPILED = {suffix: re.compile(pattern, re.M) for suffix, pattern in PATTERNS.items()}
RUST_EXTS = frozenset({".rs"})
ASSERTING_CALLS = frozenset({"raises", "warns", "fail"})


def _suffix(path: str) -> str:
    return PurePath(path.lower()).suffix


def declares_tests(path: str, text: str) -> bool:
    """File level only, because a Rust cfg(test) module beside source is judged unit by unit."""
    suffix = _suffix(path)
    if suffix in PYTHON_EXTS:
        return _python_declares(text)
    if suffix in RUST_EXTS:
        return _rust_declares(text)
    pattern = COMPILED.get(suffix)
    return bool(pattern and pattern.search(text))


def _rust_declares(text: str) -> bool:
    for block in rust_cfg_test_blocks(text):
        text = text.replace(block, "")
    return bool(RUST_TEST_RE.search(text))


def _python_declares(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return bool(PYTHON_FALLBACK_RE.search(text))
    return any(_python_test_node(node) for node in _module_statements(tree.body))


def _module_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Into if, try, and with, because a guarded definition still lands at module level."""
    for node in body:
        yield node
        if isinstance(node, BRANCHING):
            yield from _module_statements(_branches(node))


def _branches(node: ast.stmt) -> list[ast.stmt]:
    nested = [*getattr(node, "body", []), *getattr(node, "orelse", []), *getattr(node, "finalbody", [])]
    return nested + [statement for handler in getattr(node, "handlers", []) for statement in handler.body]


def _python_test_node(node: ast.AST) -> bool:
    """A bare test_ name is no proof, because only an assert or a framework makes pytest run it."""
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return any(root in PYTHON_FRAMEWORKS for root in _imported_roots(node)) or _star_import(node)
    if isinstance(node, ast.ClassDef):
        bases = {_base_name(base) for base in node.bases}
        return node.name.startswith("Test") or bool(bases & PYTHON_CASE_BASES) or any(map(_python_test_node, node.body))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name.startswith("pytest_") or _fixture(node) or (node.name.startswith("test_") and _asserts(node))
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(getattr(target, "id", "") in PYTEST_SETTINGS for target in targets)
    return False


def _star_import(node: ast.Import | ast.ImportFrom) -> bool:
    """Because pytest collects what a star import brings in, the file may run tests it never spells."""
    return any(alias.name == "*" for alias in node.names)


def _imported_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.ImportFrom):
        return [(node.module or "").split(".")[0]]
    return [alias.name.split(".")[0] for alias in node.names]


def _base_name(base: ast.expr) -> str:
    return base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")


def _fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("fixture" in ast.unparse(decorator) for decorator in node.decorator_list)


def _asserts(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(inner, ast.Assert) or _assert_call(inner) for inner in ast.walk(node))


def _assert_call(node: ast.AST) -> bool:
    """unittest and pytest.raises assert through calls, so a method name counts as well."""
    if not isinstance(node, ast.Call):
        return False
    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
    return name.startswith("assert") or name in ASSERTING_CALLS
