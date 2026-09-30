"""Discover rules here, because tickets must not edit scanner."""
from __future__ import annotations

import ast
import functools
import importlib
import pkgutil
from collections.abc import Callable, Iterable
from typing import NamedTuple

try:
    from ..findings import Finding
    from ..test_units import Unit, extract
except ImportError:
    from findings import Finding
    from test_units import Unit, extract

FAMILY = "code"
UNMEASURED_STATE = "observe"
EXPORT = "RULE_SET"


class Rule(NamedTuple):
    """Hold the wording, because every hit must name its action."""

    name: str
    detail: str
    action: str
    state: str = UNMEASURED_STATE


class Hit(NamedTuple):
    """Keep hits small, because the registry owns the finding shape."""

    rule: str
    line: int
    snippet: str


class RuleSet(NamedTuple):
    """Pair rules with check, because a hit must name a declared rule."""

    rules: tuple[Rule, ...]
    check: Callable[[Unit, str], Iterable[Hit]]


@functools.lru_cache(maxsize=32)
def module_tree(text: str) -> ast.Module | None:
    """Parse once per file, because every rule module reads the same source."""
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _exported(package: str, name: str) -> RuleSet:
    # Rule modules skip config, because config imports them.
    rule_set = getattr(importlib.import_module(package + "." + name), EXPORT, None)
    if not isinstance(rule_set, RuleSet):
        raise TypeError(f"Code Check module {name} must export {EXPORT} as a RuleSet")
    return rule_set


def discover(paths: Iterable[str], package: str) -> tuple[RuleSet, ...]:
    """Scan the package, because a new module needs no import line."""
    found = tuple(
        _exported(package, module.name)
        for module in pkgutil.iter_modules(list(paths))
        if not module.name.startswith("_")
    )
    names = [rule.name for rule_set in found for rule in rule_set.rules]
    if len(names) != len(set(names)):
        raise ValueError("two Code Check modules declare the same rule")
    return found


RULE_SETS: tuple[RuleSet, ...] = discover(__path__, __name__)


def default_gates(rule_sets: Iterable[RuleSet]) -> dict[str, str]:
    """Observe by default, because only a measured rule may block."""
    return {rule.name: rule.state for rule_set in rule_sets for rule in rule_set.rules}


def _finding(unit: Unit, rule: Rule, hit: Hit) -> dict:
    return Finding(
        family=FAMILY, rule=rule.name, line=hit.line,
        detail=rule.detail + " in " + unit.name + " in " + unit.path, force=False,
        snippet=hit.snippet.strip()[:180] or unit.name, action=rule.action,
        path=None, severity=None, tool_use_id=None,
    ).to_dict()


def _set_findings(rule_set: RuleSet, unit: Unit, text: str) -> list[dict]:
    """Reject stray names, because a typo would dodge the gate."""
    declared = {rule.name: rule for rule in rule_set.rules}
    rows: list[dict] = []
    for hit in rule_set.check(unit, text):
        if hit.rule not in declared:
            raise ValueError("Code Check hit names an undeclared rule: " + hit.rule)
        rows.append(_finding(unit, declared[hit.rule], hit))
    return rows


def unit_findings(unit: Unit, text: str, rule_sets: Iterable[RuleSet] | None = None) -> list[dict]:
    """Take a registry, because tests and the audit inject their own."""
    chosen = RULE_SETS if rule_sets is None else rule_sets
    return [row for rule_set in chosen for row in _set_findings(rule_set, unit, text)]


def check_file(path: str, text: str, rule_sets: Iterable[RuleSet] | None = None) -> list[dict]:
    """Enter here, because the scanner and the audit must match."""
    chosen = RULE_SETS if rule_sets is None else tuple(rule_sets)
    if not chosen:
        return []
    return [row for unit in extract(path, text) for row in unit_findings(unit, text, chosen)]
