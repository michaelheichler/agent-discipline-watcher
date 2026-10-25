"""Through scan_all, because a forced triad matters only as the row a writer sees, while a queue or an inventory must stay quiet."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

ENGLISH_ONLY = {"prose_languages": ["en"]}
INTRO = "Intro line here.\n\n"


def _triad_lines(body: str) -> list[int]:
    rows = scan_all("doc.md", INTRO + body, dict(ENGLISH_ONLY))
    return [row["line"] for row in rows if row["rule"] == "three_item_list"]


@pytest.mark.parametrize("body", [
    pytest.param("- Apples are red\n- Pears are green\n- Plums are dark\n", id="bullets"),
    pytest.param("1. Apples are red\n2. Pears are green\n3. Plums are dark\n", id="numbered-in-order"),
])
def test_three_short_look_alike_entries_report_a_forced_triad(body: str) -> None:
    assert _triad_lines(body) == [3]


@pytest.mark.parametrize("body", [
    pytest.param("- I-001 apples are red\n- I-002 pears are green\n- I-003 plums are dark\n", id="issue-ids"),
    pytest.param("- #12 apples are red\n- #13 pears are green\n- #14 plums are dark\n", id="hash-ids"),
    pytest.param("- Item 15 apples are red\n- Item 16 pears are green\n- Item 17 plums are dark\n", id="item-ids"),
    pytest.param("- [ ] Apples are red\n- [x] Pears are green\n- [ ] Plums are dark\n", id="checkboxes"),
    pytest.param("- Apples are red\n- Pears live in src/pears\n- Plums are dark\n", id="path"),
    pytest.param("- Apples are red\n- Pears are `green`\n- Plums are dark\n", id="inline-code"),
    pytest.param(
        "- Apples are red and they grow on the tall trees behind the old barn\n"
        "- Pears are green and they grow on the short trees beside the new barn\n"
        "- Plums are dark and they grow on the low bushes along the fence\n",
        id="long-entries"),
    pytest.param("- Apples\n- Pears are green\n- Plums grow dark and very sweet in late summer\n", id="wide-word-spread"),
    pytest.param("- Apples are red\n- pears are green\n- Plums are dark\n", id="mixed-capitals"),
    pytest.param("- Apples are red. They taste sweet\n- Pears are green\n- Plums are dark\n", id="two-sentences"),
    pytest.param("1. Apples are red\n2. Pears are green\n4. Plums are dark\n", id="numbers-skip"),
    pytest.param("- Apples are red\n- Pears are green\n  still about pears\n- Plums are dark\n", id="continued-entry"),
])
def test_a_list_that_tracks_items_or_carries_detail_draws_no_triad(body: str) -> None:
    assert _triad_lines(body) == []
