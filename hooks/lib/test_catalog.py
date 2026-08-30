from __future__ import annotations

import re

from lib import catalog, config

CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _entries() -> dict[str, catalog.Entry]:
    return {
        **catalog.RULES,
        **catalog.FAMILIES,
        **catalog.THRESHOLDS,
        **catalog.RULE_STATES,
        **catalog.FAMILY_STATES,
        **catalog.BASELINE_MODES,
    }


def test_every_gated_rule_carries_a_human_entry() -> None:
    """Cover each gated name because the screen renders a raw identifier without one."""
    gated = set(config.DEFAULTS["rule_gates"]) | set(config.ALWAYS_BLOCKING_RULES)
    missing = sorted(gated - set(catalog.RULES))

    assert missing == []


def test_the_catalog_names_no_rule_the_config_dropped() -> None:
    """Reject an orphan because a renamed rule must fail loudly, not linger."""
    gated = set(config.DEFAULTS["rule_gates"]) | set(config.ALWAYS_BLOCKING_RULES)
    orphans = sorted(set(catalog.RULES) - gated)

    assert orphans == []


def test_every_family_and_threshold_carries_an_entry() -> None:
    """Cover the other two screens because they render raw keys today."""
    assert sorted(catalog.FAMILIES) == sorted(config.GATE_FAMILIES)
    assert sorted(catalog.THRESHOLDS) == ["list_item_cap", "max_rows", "sentence_word_cap"]


def test_every_state_reads_as_a_consequence() -> None:
    """Explain each state because observe and judged mean nothing to a reader."""
    assert sorted(catalog.RULE_STATES) == sorted(config.RULE_GATE_STATES)
    assert sorted(catalog.FAMILY_STATES) == sorted(config.GATE_STATES)
    assert sorted(catalog.BASELINE_MODES) == ["git", "none", "report"]


def test_no_entry_is_empty_unbounded_or_control_bearing() -> None:
    """Bound every string because the bridge hands them straight to a terminal."""
    for name, entry in _entries().items():
        assert entry.title.strip(), name
        assert entry.description.strip(), name
        assert len(entry.title) <= 40, name
        assert len(entry.description) <= 120, name
        assert not CONTROL_RE.search(entry.title), name
        assert not CONTROL_RE.search(entry.description), name


def test_a_title_never_repeats_across_rules() -> None:
    """Keep titles distinct because two identical rows leave the reader guessing."""
    titles = [entry.title for entry in catalog.RULES.values()]

    assert len(titles) == len(set(titles))


def test_no_title_leaks_the_raw_identifier() -> None:
    """Drop the snake case because the identifier is what the reader could not parse."""
    for name, entry in catalog.RULES.items():
        assert name not in entry.title, name
        assert "_" not in entry.title, name


def test_an_unknown_name_falls_back_instead_of_raising() -> None:
    """Derive a title because a new rule must never break the configuration screen."""
    entry = catalog.rule_entry("some_future_rule")

    assert entry.title == "Some future rule"
    assert entry.description


def test_a_known_name_returns_its_written_entry() -> None:
    """Prefer the written text because the fallback carries no description."""
    assert catalog.rule_entry("banned_adverb") is catalog.RULES["banned_adverb"]
    assert catalog.family_entry("punctuation") is catalog.FAMILIES["punctuation"]
    assert catalog.state_entry("judged", locked=False) is catalog.RULE_STATES["judged"]


def test_a_locked_rule_reports_one_state_only() -> None:
    """Name the lock because an always-blocking rule offers the reader no choice."""
    entry = catalog.state_entry("enforce", locked=True)

    assert entry is catalog.LOCKED_STATE
    assert entry.title != catalog.RULE_STATES["enforce"].title


def test_a_locked_rule_reads_as_locked_rather_than_broken() -> None:
    """Show the lock wording because a greyed row with no reason reads as a bug."""
    for name in sorted(config.ALWAYS_BLOCKING_RULES):
        shown = catalog.state_entry("enforce", locked=name in catalog.LOCKED_RULES)

        assert shown.title == catalog.LOCKED_STATE.title, name
        assert "no project config can change it" in shown.description
