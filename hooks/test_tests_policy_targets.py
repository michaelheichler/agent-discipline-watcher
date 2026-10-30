"""One case per layout, because a missed name lets a test slip past the gate."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_write
from lib import protected, tests_policy
from test_tests_policy_gate import PLAIN_BODY, TEST_BODY, blocked_by, isolated, project

EditPair = tuple[str, str]
NEUTRAL = "VALUE = 1\n"
RUST_LIB = (
    "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"
    "\n"
    "#[cfg(test)]\n"
    "mod tests {\n"
    "    use super::*;\n"
    "\n"
    "    #[test]\n"
    "    fn adds() {\n"
    "        assert_eq!(add(1, 2), 3);\n"
    "    }\n"
    "}\n"
)
PYTEST_SKIP = "@pytest.mark.skip\n"
UNITTEST_SKIP = "@unittest.skip('x')\n"
PYTEST_MODULE = "import pytest\n\n\n" + PLAIN_BODY + "\n\n"
UNITTEST_SUITE = (
    "import unittest\n"
    "\n"
    "\n"
    "class TotalTest(unittest.TestCase):\n"
    "    def double(value):\n"
    "        return value * 2\n"
    "\n"
    "    def test_total(self):\n"
    "        self.assertEqual(sum([1, 2]), 3)\n"
)
RUST_LOOSE_TEST = (
    "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"
    "\n"
    "#[test]\n"
    "fn adds() {\n"
    "    assert_eq!(add(1, 2), 3);\n"
    "}\n"
)
MODULES_WITH_TESTS = {
    "src/lib.rs": RUST_LIB,
    "total.py": PLAIN_BODY + "\n\n" + TEST_BODY,
    "src/total.py": PYTEST_MODULE + TEST_BODY,
    "src/skipped.py": PYTEST_MODULE + PYTEST_SKIP + TEST_BODY,
    "src/suite.py": UNITTEST_SUITE,
    "src/loose.rs": RUST_LOOSE_TEST,
}
RUST_TEST_FN ="    #[test]\n    fn adds() {\n        assert_eq!(add(1, 2), 3);\n    }\n"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def write_from(cwd: Path, target: Path, content: str) -> dict:
    payload = {"session_id": "t33", "cwd": str(cwd), "tool_name": "Write",
               "tool_input": {"file_path": str(target), "content": content}}
    return pre_write.run(payload, isolated(cwd))


def edit(cwd: Path, relative: str, edit_pair: EditPair) -> dict:
    old, new = edit_pair
    payload = {"session_id": "t32", "cwd": str(cwd), "tool_name": "Edit", "tool_input": {
        "file_path": str(cwd / relative), "old_string": old, "new_string": new}}
    return pre_write.run(payload, isolated(cwd))


def seeded(tmp_path: Path, relative: str) -> Path:
    cwd = project(tmp_path, tests="deny")
    (cwd / relative).parent.mkdir(parents=True, exist_ok=True)
    (cwd / relative).write_text(MODULES_WITH_TESTS[relative], encoding="utf-8")
    return cwd


def project_under_tests_folder(tmp_path: Path) -> Path:
    root = tmp_path / "tests" / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "tests").mkdir()
    return project(root, tests="deny")


def test_a_source_file_in_a_project_under_a_tests_folder_passes(tmp_path: Path) -> None:
    root = project_under_tests_folder(tmp_path)
    assert not blocked_by(write_from(root, root / "src" / "app.py", PLAIN_BODY), tests_policy.RULE)


def test_the_tests_dir_inside_that_project_still_blocks(tmp_path: Path) -> None:
    root = project_under_tests_folder(tmp_path)
    assert blocked_by(write_from(root, root / "tests" / "x.py", NEUTRAL), tests_policy.RULE)


def test_a_session_started_inside_the_tests_dir_still_blocks(tmp_path: Path) -> None:
    root = project_under_tests_folder(tmp_path)
    response = write_from(root / "tests", root / "tests" / "x.py", NEUTRAL)
    assert blocked_by(response, tests_policy.RULE)


def test_a_tests_dir_outside_the_project_blocks(tmp_path: Path) -> None:
    root = project_under_tests_folder(tmp_path)
    outside = tmp_path / "scratch" / "tests" / "x.py"
    assert blocked_by(write_from(root, outside, NEUTRAL), tests_policy.RULE)


@pytest.mark.parametrize("relative", [
    "test/foo.js",
    "src/test/java/FooTest.java",
    "spec/foo_spec.rb",
    "conftest.py",
    "tests/fixture.json",
])
def test_deny_blocks_a_test_file_of_another_layout(tmp_path: Path, relative: str) -> None:
    cwd = project(tmp_path, tests="deny")
    assert blocked_by(write_from(cwd, cwd / relative, NEUTRAL), tests_policy.RULE)


@pytest.mark.parametrize(("relative", "content"), [
    pytest.param("pkg/foo_test.go", 'package foo\n\nimport "testing"\n\nfunc TestValue(t *testing.T) {}\n', id="go"),
    pytest.param("src/BarTests.java", "import org.junit.jupiter.api.Test;\n\nclass BarTests {\n    @Test\n    void adds() {}\n}\n",
                 id="java"),
])
def test_deny_blocks_a_declared_test_under_a_test_name(tmp_path: Path, relative: str, content: str) -> None:
    cwd = project(tmp_path, tests="deny")
    assert blocked_by(write_from(cwd, cwd / relative, content), tests_policy.RULE)


@pytest.mark.parametrize(("relative", "content"), [
    pytest.param("pkg/foo_test.go", "package foo\n\nconst Value = 1\n", id="go"),
    pytest.param("src/BarTests.java", "class BarTests {\n    static final int VALUE = 1;\n}\n", id="java"),
    pytest.param("hooks/lib/test_source.py", "import re\nPATTERN = re.compile('x')\n", id="python-module"),
])
def test_deny_passes_code_without_a_test_under_a_test_name(tmp_path: Path, relative: str, content: str) -> None:
    cwd = project(tmp_path, tests="deny")
    assert not blocked_by(write_from(cwd, cwd / relative, content), tests_policy.RULE)


@pytest.mark.parametrize("relative", [
    "src/testing_utils.go",
    "contest.py",
    "src/Contest.java",
    "docs/spec/design.md",
    "tests/README.md",
])
def test_deny_passes_a_lookalike_or_a_document(tmp_path: Path, relative: str) -> None:
    cwd = project(tmp_path, tests="deny")
    assert not blocked_by(write_from(cwd, cwd / relative, NEUTRAL), tests_policy.RULE)


@pytest.mark.parametrize(("relative", "edit_pair"), [
    ("src/lib.rs", ("{ a + b }", "{ b + a }")),
    ("src/lib.rs", ("pub fn add", "pub fn zero() -> i32 { 0 }\n\npub fn add")),
    ("total.py", ("return sum(values)", "return sum(values, 0)")),
    ("total.py", ("def total", "def zero():\n    return 0\n\n\ndef total")),
    ("src/suite.py", ("    def double", "    @staticmethod\n    def double")),
    ("src/skipped.py", ("import pytest\n", "\n\nimport pytest\n")),
    ("src/loose.rs", ("pub fn add", "#[inline]\npub fn add")),
], ids=["rust-body", "rust-shifts-tests", "python-body", "python-shifts-tests", "python-helper-decorator",
        "python-shifts-decorated-test", "rust-helper-attribute"])
def test_deny_passes_an_edit_that_leaves_inline_tests_alone(tmp_path: Path, relative: str, edit_pair: EditPair) -> None:
    cwd = seeded(tmp_path, relative)
    assert not blocked_by(edit(cwd, relative, edit_pair), tests_policy.RULE)


@pytest.mark.parametrize(("relative", "edit_pair"), [
    ("src/total.py", ("def test_total", PYTEST_SKIP + "def test_total")),
    ("src/skipped.py", (PYTEST_SKIP, "")),
    ("src/suite.py", ("    def test_total", "    " + UNITTEST_SKIP + "    def test_total")),
    ("src/suite.py", ("class TotalTest", UNITTEST_SKIP + "class TotalTest")),
    ("src/loose.rs", ("#[test]\n", "#[test]\n#[ignore]\n")),
    ("src/loose.rs", ("#[test]\n", "#[ignore]\n#[test]\n")),
], ids=["pytest-skip-added", "pytest-skip-removed", "unittest-skip-on-test", "unittest-skip-on-class",
        "rust-ignore-after-test", "rust-ignore-before-test"])
def test_deny_blocks_a_skip_marker_change_on_an_inline_test(tmp_path: Path, relative: str, edit_pair: EditPair) -> None:
    cwd = seeded(tmp_path, relative)
    assert blocked_by(edit(cwd, relative, edit_pair), tests_policy.RULE)


@pytest.mark.parametrize(("old", "new"), [
    ("assert_eq!(add(1, 2), 3);", "assert_eq!(add(2, 1), 3);"),
    (RUST_TEST_FN, ""),
    ("use super::*;", "use super::add;"),
    ("    #[test]\n", "    #[test]\n    #[ignore]\n"),
], ids=["test-body", "test-deleted", "tests-module-import", "ignore-attribute"])
def test_deny_blocks_an_edit_inside_the_rust_tests_module(tmp_path: Path, old: str, new: str) -> None:
    cwd = seeded(tmp_path, "src/lib.rs")
    assert blocked_by(edit(cwd, "src/lib.rs", (old, new)), tests_policy.RULE)
