"""A rule at the judged gate needs a reader before it speaks, because 278 of 60000 human sentences carry an ordinary three-item series."""
from __future__ import annotations

from typing import NamedTuple

try:
    from .config import JUDGED_STATE, effective_config, rule_state
    from .judge_model import judge_model
    from .pattern_judge import PatternCandidate, confirm_all
    from .pattern_semantic import load_exemplars, load_manifest, rule_prompt
except ImportError:
    from config import JUDGED_STATE, effective_config, rule_state
    from judge_model import judge_model
    from pattern_judge import PatternCandidate, confirm_all
    from pattern_semantic import load_exemplars, load_manifest, rule_prompt


class JudgedFinding(NamedTuple):
    rule: str
    line: int
    text: str


def judged_rules(config: dict | None = None) -> frozenset[str]:
    cfg = effective_config(config)
    gates = cfg.get("rule_gates")
    if not isinstance(gates, dict):
        return frozenset()
    return frozenset(rule for rule in gates if rule_state(rule, cfg) == JUDGED_STATE)


def _candidates(path: str, findings: list[dict], rule: str) -> tuple[PatternCandidate, ...]:
    return tuple(
        PatternCandidate(path, int(finding.get("line") or 0), str(finding.get("snippet") or ""))
        for finding in findings
        if finding.get("rule") == rule and finding.get("snippet")
    )


def confirm(path: str, findings: list[dict], config: dict | None = None) -> tuple[JudgedFinding, ...]:
    """An unavailable judge confirms nothing, because an unread hit on this gate would report ordinary prose as slop."""
    rules = judged_rules(config) & {str(finding.get("rule")) for finding in findings}
    if not rules:
        return ()
    exemplars = load_exemplars()
    manifest = load_manifest()
    named = tuple(rule for rule in sorted(rules) if rule in manifest["rules"])
    work = tuple(
        (rule_prompt(rule, exemplars, manifest), _candidates(path, findings, rule))
        for rule in named
    )
    model = judge_model(effective_config(config).get("adw_model"))
    return tuple(
        JudgedFinding(rule, candidate.line, candidate.text)
        for rule, kept in sorted(confirm_all(work, model).items())
        for candidate in kept
    )
