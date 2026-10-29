"""Kept apart from test_scanner.py, because that file sits at its length limit and these cases only judge which expect forms assert."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all


@pytest.mark.parametrize(("body", "hollow"), [
    pytest.param("  await expect.poll(() => calls).toMatchObject([{ a: 1 }]);\n", False, id="entry-8s-expect-poll"),
    pytest.param("  expect.soft(x).toBe(1);\n", False, id="expect-soft"),
    pytest.param("", True, id="empty-body"),
    pytest.param("  const matcher = expect.any(Number);\n", True, id="asymmetric-matcher-only"),
])
def test_expect_poll_and_soft_count_as_assertions_and_a_bare_matcher_does_not(body: str, hollow: bool) -> None:
    text = f"test('a', async () => {{\n{body}}});\n"
    rules = {item["rule"] for item in scan_all("x.spec.ts", text, {"punctuation": False, "english": False})}
    assert ("hollow_test" in rules) is hollow
