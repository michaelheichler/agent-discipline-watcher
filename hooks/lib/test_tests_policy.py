"""Change in, verdict out, because touches_tests decides which evidence wins before any payload is read."""
from __future__ import annotations

import pytest

from lib import tests_policy

TEST_BODY = "def test_total():\n    assert total([1, 2]) == 3\n"
DESCRIBE = "describe('x', () => {})\n"


def touches(path: str, before: str | None, after: str | None) -> bool:
    return tests_policy.touches_tests(tests_policy.PendingChange(path, before, after))


@pytest.mark.parametrize(("path", "before", "after"), [
    pytest.param("pkg/total_test.py", "x = 1\n", None, id="unknown-landing-under-a-test-name"),
    pytest.param("tests/data.json", None, None, id="unknown-landing-under-a-test-folder"),
    pytest.param("tests/helpers.py", None, "def helper(a, b): pass\n", id="helper-code-in-tests"),
    pytest.param("tests/fixture.json", None, '{"a": 1}\n', id="fixture-data-in-tests"),
    pytest.param("spec/support/helpers.rb", None, "x = 1\n", id="support-code-in-spec"),
    pytest.param("pkg/testdata/expected.golden", None, "x\n", id="golden-file-in-testdata"),
    pytest.param("pkg/testdata/golden.txt", None, "x\n", id="text-expected-output-in-testdata"),
    pytest.param("web/__snapshots__/cart.ts.snap", None, "x\n", id="jest-snapshot-folder"),
    pytest.param("web/__fixtures__/user.json", None, "{}\n", id="jest-fixture-folder"),
    pytest.param("web/__mocks__/fs.js", None, "module.exports = {}\n", id="jest-mock-folder"),
    pytest.param("tests/helpers.py", "def helper(): pass\n", "", id="helper-emptied-in-tests"),
    pytest.param("conftest.py", None, "VALUE = 1\n", id="conftest-without-a-test"),
    pytest.param("pkg/conftest.py", "VALUE = 1\n", "VALUE = 2\n", id="nested-conftest-edit"),
    pytest.param("pkg/total_test.py", None, TEST_BODY, id="declared-test-under-a-test-name"),
    pytest.param("src/checks.ts", None, DESCRIBE, id="declared-test-in-a-language-without-units"),
    pytest.param("pkg/util.go", None, "func TestX(t *testing.T) {}\n", id="go-test-under-a-plain-name"),
    pytest.param("src/checks.ts", DESCRIBE, "export const x = 1\n", id="declared-test-removed"),
    pytest.param(
        "web/cart.test.ts", None, "it.each([[1, 2]])('adds %d', (a, b) => { expect(a + 1).toBe(b) })\n",
        id="jest-each-table-without-import",
    ),
])
def test_a_change_with_test_evidence_touches_tests(path: str, before: str | None, after: str | None) -> None:
    assert touches(path, before, after)


@pytest.mark.parametrize(("path", "before", "after"), [
    pytest.param("src/total.py", "x = 1\n", None, id="unknown-landing-under-a-plain-name"),
    pytest.param("tests/test_x.py", TEST_BODY, TEST_BODY, id="unchanged-test-file"),
    pytest.param("tests/__init__.py", None, "", id="empty-package-marker-in-tests"),
    pytest.param("tests/helpers.py", None, "  \n", id="whitespace-only-in-tests"),
    pytest.param("conftest.py", None, "", id="empty-conftest"),
    pytest.param("tests/README.md", None, "text\n", id="document-in-tests"),
    pytest.param("docs/spec/design.md", None, "text\n", id="document-in-spec"),
    pytest.param("hooks/lib/test_source.py", None, "import re\nPATTERN = re.compile('x')\n", id="module-under-a-test-name"),
    pytest.param(
        "src/total.py", "import pytest\n\ndef total():\n    return 1\n", "import pytest\n\ndef total():\n    return 2\n",
        id="framework-import-beside-an-untouched-unit",
    ),
])
def test_a_change_without_test_evidence_leaves_tests_alone(path: str, before: str | None, after: str | None) -> None:
    assert not touches(path, before, after)
