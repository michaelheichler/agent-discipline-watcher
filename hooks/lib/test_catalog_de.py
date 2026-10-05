from __future__ import annotations

import re

from lib import catalog, catalog_de, config, german_punctuation, test_rules

CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _english_only() -> set[str]:
    """Exclude these because code comments keep English (decision Q3) and German never raises the colon or semicolon ban."""
    return (
        set(config.ALWAYS_BLOCKING_RULES)
        | set(config.FIXED_OBSERVE_RULES)
        | set(test_rules.default_gates(test_rules.RULE_SETS))
        | {"function_too_long", "hollow_test", "deferred_work_comment"}
        | set(german_punctuation.ENGLISH_ONLY_RULES)
    )


def _catalogued() -> set[str]:
    return set(catalog.RULES) | set(catalog.UNGATED_RULES)


def _malformed(entry: catalog_de.GermanEntry) -> bool:
    texts = (entry.title, entry.description, entry.action)
    blank = not all(text.strip() for text in texts)
    controlled = any(CONTROL_RE.search(text) for text in texts)
    return blank or controlled or len(entry.title) > 40 or len(entry.description) > 120


def test_every_rule_a_german_paragraph_can_raise_carries_german_wording() -> None:
    """Cover each prose rule because a German row without wording falls back to English text."""
    missing = sorted(_catalogued() - _english_only() - set(catalog_de.RULES))

    assert missing == []


def test_the_german_catalog_names_no_rule_the_english_catalog_dropped() -> None:
    """Reject an orphan because a renamed rule must fail loudly in both languages."""
    orphans = sorted(set(catalog_de.RULES) - _catalogued())

    assert orphans == []


def test_no_german_entry_is_empty_unbounded_or_control_bearing() -> None:
    """Bound every string because the hosts hand them straight to a terminal."""
    malformed = sorted(name for name, entry in catalog_de.RULES.items() if _malformed(entry))

    assert malformed == []


def test_a_german_title_never_repeats_across_rules() -> None:
    """Keep titles distinct because two identical rows leave the reader guessing."""
    titles = [entry.title for entry in catalog_de.RULES.values()]

    assert len(titles) == len(set(titles))
