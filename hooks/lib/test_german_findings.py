from __future__ import annotations

import json
from functools import partial
from pathlib import Path

from lib import catalog, catalog_de, principle_kb, reporting, session_state
from lib.finding_output import Explainer
from lib.findings import Outcome

GERMAN_RULE = "genitive_apostrophe"
ENGLISH_RULE = "banned_dash"


def _row(rule: str, language: str, line: int) -> dict:
    return {
        "path": "notes.md", "line": line, "family": "punctuation", "rule": rule,
        "detail": "English detail in notes.md", "snippet": "Peter's Haus", "match": "x",
        "action": "English action.", "language": language,
    }


def _lines(findings: list[dict]) -> list[str]:
    reason, _ = reporting.compact_block(findings, {})
    return reason.split("\n")


def test_one_report_renders_each_row_in_its_own_language() -> None:
    """Pick the language per row because one file can hold a German and an English paragraph."""
    german = catalog_de.RULES[GERMAN_RULE]
    english = catalog.rule_entry(ENGLISH_RULE)

    lines = _lines([_row(GERMAN_RULE, "de", 1), _row(ENGLISH_RULE, "en", 2)])

    assert lines[1:3] == [
        f'1. notes.md:1 {german.title} "x". {german.action} ({GERMAN_RULE})',
        f'2. notes.md:2 {english.title} "x". English action. ({ENGLISH_RULE})',
    ]


def test_a_mixed_report_keeps_the_english_lead_and_tail() -> None:
    """Keep the block lines English because a German lead would mislabel the English row beside it."""
    reason, report = reporting.compact_block([_row(GERMAN_RULE, "de", 1), _row(ENGLISH_RULE, "en", 2)], {})
    lines = reason.split("\n")

    assert (lines[0], lines[-1]) == (reporting.BLOCK_LEAD, f"Full report: {report}")


def test_an_all_german_report_leads_and_ends_in_german() -> None:
    """Switch the block lines because the message itself shows the reader which language ADW detected."""
    reason, report = reporting.compact_block([_row(GERMAN_RULE, "de", 1)], {})
    lines = reason.split("\n")

    assert (lines[0], lines[-1]) == (catalog_de.BLOCK_LEAD, f"{catalog_de.FULL_REPORT}: {report}")


def test_an_observed_german_report_uses_the_german_observe_lead() -> None:
    """Translate the observe lead too because it carries the instruction the agent acts on."""
    _kind, message = reporting.verdict_message([(_row(GERMAN_RULE, "de", 1), Outcome.WOULD_BLOCK)], {})

    assert message.split("\n")[0] == catalog_de.OBSERVE_LEAD


def test_the_full_report_carries_the_german_detail_and_action() -> None:
    """Translate the stored rows because the agent reads the full report when the block is cut."""
    _reason, report = reporting.compact_block([_row(GERMAN_RULE, "de", 1)], {})
    stored = json.loads(Path(report).read_text(encoding="utf-8"))[0]
    german = catalog_de.RULES[GERMAN_RULE]

    assert (stored["detail"], stored["action"]) == (f"{german.title} in notes.md", german.action)


def test_a_german_row_without_german_wording_stays_english() -> None:
    """Fall back whole because a half-translated row reads worse than an English one."""
    lines = _lines([_row("some_future_rule", "de", 1)])

    assert lines[0] == reporting.BLOCK_LEAD
    assert lines[1].endswith('"x". English action. (some_future_rule)')


def test_a_german_row_labels_its_principle_in_german(tmp_path: Path) -> None:
    """Translate the label because the principle body comes from an English source."""
    row = principle_kb.Row("deviq", "terms/x", "plain-words", "Short words read faster.")
    claim = partial(session_state.claim_explained, "s1", root=tmp_path)
    explainer = Explainer(lambda _entry: row, claim, {GERMAN_RULE: "terms/x"})

    reason, _ = reporting.compact_block([_row(GERMAN_RULE, "de", 1)], {}, explainer=explainer)

    assert reason.split("\n")[2] == f"   {catalog_de.PRINCIPLE_LABEL} (DevIQ, Plain Words): Short words read faster."
