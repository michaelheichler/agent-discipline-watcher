"""Discover German rules here, because a new rule must not edit the scanner, the catalogs, or config."""
from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable, Iterable
from typing import NamedTuple

try:
    from ..findings import Finding
    from ..prose_language import ParagraphLanguage
except ImportError:
    from findings import Finding
    from prose_language import ParagraphLanguage

FAMILY = "english"
UNMEASURED_STATE = "observe"
EXPORT = "RULE_SET"


class Wording(NamedTuple):
    """Hold one language, because the English and German screens each need all three parts."""

    title: str
    description: str
    action: str


class Rule(NamedTuple):
    """Carry both languages, because German findings speak German while the id stays English (decision Q14)."""

    name: str
    english: Wording
    german: Wording
    state: str = UNMEASURED_STATE
    boundary: str = ""
    trigger: str = ""


class Hit(NamedTuple):
    """Keep hits small, because the registry owns the finding shape."""

    rule: str
    line: int
    snippet: str
    match: str


def no_hits(_path: str, _paragraphs: list[ParagraphLanguage]) -> Iterable[Hit]:
    """Find nothing, because the embedding vote and the judge find a SEMANTIC rule, not a pattern."""
    return ()


class RuleSet(NamedTuple):
    """Pair rules with check, because a hit must name a declared rule."""

    rules: tuple[Rule, ...]
    check: Callable[[str, list[ParagraphLanguage]], Iterable[Hit]] = no_hits
    voted: bool = False


def _exported(package: str, name: str) -> RuleSet:
    rule_set = getattr(importlib.import_module(package + "." + name), EXPORT, None)
    if not isinstance(rule_set, RuleSet):
        raise TypeError(f"German rule module {name} must export {EXPORT} as a RuleSet")
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
        raise ValueError("two German rule modules declare the same rule")
    return found


RULE_SETS: tuple[RuleSet, ...] = discover(__path__, __name__)


def declared(rule_sets: Iterable[RuleSet] | None = None) -> tuple[Rule, ...]:
    """List every rule, because the two catalogs read their wording from here."""
    chosen = RULE_SETS if rule_sets is None else rule_sets
    return tuple(rule for rule_set in chosen for rule in rule_set.rules)


def voted(rule_sets: Iterable[RuleSet] | None = None) -> tuple[Rule, ...]:
    """List the SEMANTIC rules, because only these take German exemplars and the German rubric."""
    chosen = RULE_SETS if rule_sets is None else rule_sets
    return tuple(rule for rule_set in chosen if rule_set.voted for rule in rule_set.rules)


def triggers(rule_sets: Iterable[RuleSet] | None = None) -> dict[str, re.Pattern[str]]:
    """One source, because the labels cover the candidates these patterns drew and the hook must draw the same ones."""
    return {rule.name: re.compile(rule.trigger, re.IGNORECASE) for rule in voted(rule_sets) if rule.trigger}


def default_gates(rule_sets: Iterable[RuleSet] | None = None) -> dict[str, str]:
    """Observe by default, because only a rule that clears the 0.85 bar may block (decision Q23)."""
    return {rule.name: rule.state for rule in declared(rule_sets)}


def _finding(path: str, rule: Rule, hit: Hit) -> dict:
    return Finding(
        family=FAMILY, rule=rule.name, line=hit.line,
        detail=rule.english.title + " in " + path, force=False,
        snippet=hit.snippet.strip()[:180] or hit.match, action=rule.english.action,
        path=None, severity=None, tool_use_id=None, match=hit.match,
    ).to_dict()


def _set_findings(rule_set: RuleSet, path: str, paragraphs: list[ParagraphLanguage]) -> list[dict]:
    """Reject stray names, because a typo would dodge the gate."""
    named = {rule.name: rule for rule in rule_set.rules}
    rows: list[dict] = []
    for hit in rule_set.check(path, paragraphs):
        if hit.rule not in named:
            raise ValueError("German rule hit names an undeclared rule: " + hit.rule)
        rows.append(_finding(path, named[hit.rule], hit))
    return rows


def check_paragraphs(path: str, paragraphs: list[ParagraphLanguage], rule_sets: Iterable[RuleSet] | None = None) -> list[dict]:
    """Enter here, because the scanner hands over only the German paragraphs."""
    chosen = RULE_SETS if rule_sets is None else tuple(rule_sets)
    if not paragraphs:
        return []
    return [row for rule_set in chosen for row in _set_findings(rule_set, path, paragraphs)]
