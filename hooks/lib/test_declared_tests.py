"""Path and text in, verdict out, because a declared test is the proof the gate reads."""
from __future__ import annotations

import pytest

from lib import declared_tests


@pytest.mark.parametrize(("path", "text"), [
    pytest.param("helpers.py", "import pytest\n", id="python-pytest-import"),
    pytest.param("helpers.py", "from unittest import mock\n", id="python-unittest-import"),
    pytest.param("helpers.py", "import hypothesis.strategies as st\n", id="python-hypothesis-submodule"),
    pytest.param("helpers.py", "import doctest\n", id="python-doctest-import"),
    pytest.param("steps.py", "from behave import given\n", id="python-behave-import"),
    pytest.param("steps.py", "from pytest_bdd import scenario\n", id="python-pytest-bdd-import"),
    pytest.param("checks.py", "class TestTotal:\n    pass\n", id="python-test-class-without-base"),
    pytest.param("checks.py", "class TotalCase(TestCase):\n    pass\n", id="python-testcase-base"),
    pytest.param("checks.py", "class TotalCase(django.test.TestCase):\n    pass\n", id="python-dotted-testcase-base"),
    pytest.param("support.py", "@fixture\ndef repo():\n    return 1\n", id="python-fixture"),
    pytest.param("support.py", "def pytest_configure(config):\n    return config\n", id="python-pytest-hook"),
    pytest.param("support.py", "from helpers import *\n", id="python-star-import"),
    pytest.param("support.py", "pytestmark = []\n", id="python-pytestmark"),
    pytest.param("support.py", "collect_ignore = ['x']\n", id="python-collect-ignore"),
    pytest.param("support.py", "__test__: bool = True\n", id="python-annotated-test-flag"),
    pytest.param("checks.py", "def test_total():\n    assert total() == 1\n", id="python-test-with-assert"),
    pytest.param("checks.py", "def test_total(self):\n    self.assertEqual(total(), 1)\n", id="python-test-with-assert-call"),
    pytest.param("checks.py", "def test_total():\n    with raises(ValueError):\n        total()\n", id="python-test-with-raises"),
    pytest.param("checks.py", "async def test_total():\n    fail('x')\n", id="python-async-test-with-fail"),
    pytest.param("checks.py", "if True:\n    def test_total():\n        assert total()\n", id="python-test-under-if"),
    pytest.param("checks.py", "try:\n    pass\nexcept ImportError:\n    import pytest\n", id="python-import-in-handler"),
    pytest.param("checks.py", "with context():\n    pytestmark = []\n", id="python-setting-under-with"),
    pytest.param("checks.py", "import pytest\ndef broken(:\n", id="python-unparsable-with-framework-import"),
    pytest.param("cart.ts", "describe('cart', () => {})\n", id="ts-describe"),
    pytest.param("cart.tsx", "import { test } from 'vitest'\n", id="tsx-vitest-import"),
    pytest.param("cart.js", "const { test } = require('node:test')\n", id="js-node-test-require"),
    pytest.param("cart.mjs", "it.skip('adds', () => {})\n", id="mjs-chained-it"),
    pytest.param("cart.ts", "it.each([[1, 2]])('adds %d', (a, b) => {})\n", id="ts-it-each-table"),
    pytest.param("cart.ts", "test.each`a`('adds', () => {})\n", id="ts-test-each-template"),
    pytest.param("cart.ts", "describe.each([1])('x', () => {})\n", id="ts-describe-each"),
    pytest.param("util.go", 'import "testing"\n', id="go-testing-import"),
    pytest.param("util.go", 'import (\n\t"fmt"\n\t"testing"\n)\n', id="go-grouped-testing-import"),
    pytest.param("util.go", "func TestTotal(t *T) {}\n", id="go-test-function"),
    pytest.param("util.go", "func Test(t *testing.T) {}\n", id="go-bare-test-function"),
    pytest.param("util.go", "func Test_total(t *testing.T) {}\n", id="go-underscore-test-function"),
    pytest.param("lib.rs", "#[test]\nfn adds() {}\n", id="rust-loose-test"),
    pytest.param("lib.rs", "#[tokio::test]\nasync fn adds() {}\n", id="rust-tokio-test"),
    pytest.param("cart.rb", "RSpec.describe Cart do\nend\n", id="ruby-rspec"),
    pytest.param("cart.rb", "class CartTest < Minitest::Test\nend\n", id="ruby-minitest"),
    pytest.param("Cart.java", "class Cart {\n    @Test\n    void adds() {}\n}\n", id="java-test-annotation"),
    pytest.param("Cart.kt", "import kotlin.test.Test\n", id="kotlin-test-import"),
    pytest.param("Cart.cs", "using Xunit;\n", id="csharp-xunit"),
    pytest.param("Cart.cs", "class Cart {\n    [Fact]\n    public void Adds() {}\n}\n", id="csharp-fact"),
    pytest.param("Cart.php", "class CartCheck extends TestCase {}\n", id="php-testcase"),
    pytest.param("Cart.swift", "import XCTest\n", id="swift-xctest"),
    pytest.param("cart.exs", "use ExUnit.Case\n", id="elixir-exunit"),
    pytest.param("cart.cc", "#include <gtest/gtest.h>\n", id="cpp-gtest-include"),
    pytest.param("cart.c", "TEST(Cart, Adds) {}\n", id="c-test-macro"),
    pytest.param("cart.dart", "import 'package:test/test.dart';\n", id="dart-test-package"),
    pytest.param("cart.bats", '@test "adds" {\n}\n', id="bats-test"),
    pytest.param("cart.sh", ". ./shunit2\n", id="shunit2-source"),
    pytest.param("cart.lua", "describe('cart', function() end)\n", id="lua-busted"),
    pytest.param("cart.ts.snap", "exports[`cart 1`] = `x`;\n", id="jest-snapshot"),
])
def test_a_file_that_declares_a_test_is_recognized(path: str, text: str) -> None:
    assert declared_tests.declares_tests(path, text)


@pytest.mark.parametrize(("path", "text"), [
    pytest.param("luna_runtime.py", "def test_runtime_or_current(root=None):\n    return root\n", id="python-bare-test-name"),
    pytest.param("test_source.py", "import re\nPATTERN = re.compile('x')\n", id="python-module-under-test-name"),
    pytest.param("checks.py", "class TotalCase(Base):\n    pass\n", id="python-ordinary-class"),
    pytest.param("checks.py", "def total(\n", id="python-unparsable-without-test"),
    pytest.param("cart.ts", "export const total = (a, b) => a + b\n", id="ts-module"),
    pytest.param("util.go", "package util\n\nfunc Total() int { return 1 }\n", id="go-module"),
    pytest.param("util.go", "func Testify() {}\n", id="go-lowercase-after-test-prefix"),
    pytest.param("cart.ts", "const items = list.each(x)\n", id="ts-each-on-a-list"),
    pytest.param("lib.rs", "#[cfg(test)]\nmod tests {\n    #[test]\n    fn adds() {}\n}\n", id="rust-cfg-test-module"),
    pytest.param("lib.rs", "pub fn add() -> i32 { 2 }\n", id="rust-module"),
    pytest.param("cart.rb", "class Cart\nend\n", id="ruby-class"),
    pytest.param("Cart.java", "class Cart {\n    static final int VALUE = 1;\n}\n", id="java-class"),
    pytest.param("Cart.swift", "import Foundation\n", id="swift-module"),
    pytest.param("cart.c", "#include <stdio.h>\n", id="c-module"),
    pytest.param("cart.sh", "echo done\n", id="shell-script"),
    pytest.param("notes.txt", "describe('cart', () => {})\n", id="unread-suffix"),
])
def test_a_file_without_a_test_declaration_is_not_recognized(path: str, text: str) -> None:
    assert not declared_tests.declares_tests(path, text)
