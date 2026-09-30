"""Pin the structure rules, because each must spare a plain guard clause."""
from __future__ import annotations

from lib import test_rules
from lib.test_rules import structure

VIOLATING_PYTHON = '''def test_check_returns_expected_result() -> None:
    result = sut.check(input_value)
    if input_value > 0:
        assert result is True
    else:
        assert result is False
'''

CLEAN_PYTHON = '''import pytest


@pytest.mark.parametrize("input_value,expected", [(5, True), (-5, False)])
def test_check_returns_expected_result(input_value, expected) -> None:
    assert sut.check(input_value) == expected
'''

GUARD_SKIP_PYTHON = '''def test_uses_the_real_binary() -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    assert convert("in.mp4") == "out.mp4"
'''

VIOLATING_RUST = '''#[test]
fn check_returns_expected_result() {
    let result = sut.check(input);
    if input > 0 {
        assert!(result);
    } else {
        assert!(!result);
    }
}
'''

CLEAN_RUST = '''#[test]
fn uses_the_real_binary() {
    if which("ffmpeg").is_none() {
        return;
    }
    assert_eq!(convert("in.mp4"), "out.mp4");
}
'''


def _hits(path: str, source: str) -> list[tuple[str, int]]:
    rows = test_rules.check_file(path, source, (structure.RULE_SET,))
    return [(row["rule"], row["line"]) for row in rows]


def test_a_python_if_else_that_asserts_on_each_side_is_flagged() -> None:
    assert _hits("tests/test_check.py", VIOLATING_PYTHON) == [("if_statements_in_tests", 3)]


def test_a_parametrized_python_test_has_no_branch_to_flag() -> None:
    assert _hits("tests/test_check.py", CLEAN_PYTHON) == []


def test_a_skip_guard_with_no_else_is_spared() -> None:
    assert _hits("tests/test_check.py", GUARD_SKIP_PYTHON) == []


def test_a_rust_if_else_that_asserts_on_each_side_is_flagged() -> None:
    assert _hits("src/check.rs", VIOLATING_RUST) == [("if_statements_in_tests", 4)]


def test_a_rust_return_guard_with_no_else_is_spared() -> None:
    assert _hits("src/check.rs", CLEAN_RUST) == []
