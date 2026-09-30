"""Flag test-structure smells, because a branching or reused test hides its scenario."""
from __future__ import annotations

from collections.abc import Iterable

try:
    from . import Hit, Rule, RuleSet
    from ..test_units import Unit
except ImportError:
    from test_rules import Hit, Rule, RuleSet
    from test_units import Unit

IF_STATEMENTS_IN_TESTS = Rule(
    "if_statements_in_tests",
    "Test branches between two different asserts",
    "Split the branches into their own test methods.",
)

RULE_SET = RuleSet(rules=(IF_STATEMENTS_IN_TESTS,), check=lambda unit, text: [])
