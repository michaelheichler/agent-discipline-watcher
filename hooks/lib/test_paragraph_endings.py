"""The rule is pinned to its record rather than to a chosen number, because the cuts come from 30700 real paragraph endings."""
from __future__ import annotations

import json
from pathlib import Path

from lib import prose_structure
from lib.scanner import scan_all

RECORD_PATH = Path(__file__).resolve().parents[2] / "evals" / "paragraph_endings.json"
RULE = "uniform_paragraph_endings"
LONG_OPENER = (
    "The model reads clinical, genomic and imaging data in one representation and forecasts "
    "relapse from it, which is the question the whole project turns on."
)
SHORT_CLOSER = "Measuring it decides everything."
LONG_CLOSER = (
    "Measuring that representation is the work, and it has occupied the group since the first "
    "cohort arrived in the spring of the following year."
)


def _document(closer: str) -> str:
    return "\n\n".join(f"{LONG_OPENER} {closer}" for _ in range(4)) + "\n"


def test_a_document_that_ends_every_paragraph_short_is_named() -> None:
    rules = {row["rule"] for row in scan_all("sample.md", _document(SHORT_CLOSER), {})}

    assert RULE in rules


def test_a_document_that_ends_on_its_long_sentence_is_left_alone() -> None:
    rules = {row["rule"] for row in scan_all("sample.md", _document(LONG_CLOSER), {})}

    assert RULE not in rules


def test_two_adjacent_blocks_in_markup_count_as_two_paragraphs() -> None:
    blocks = "\n".join(f'  <p style="margin:0">{LONG_OPENER} {SHORT_CLOSER}</p>' for _ in range(4))
    html = f"<html>\n<body>\n<section>\n{blocks}\n</section>\n</body>\n</html>\n"

    assert RULE in {row["rule"] for row in scan_all("letter.html", html, {})}


def test_too_few_paragraphs_to_measure_stay_silent() -> None:
    text = "\n\n".join(f"{LONG_OPENER} {SHORT_CLOSER}" for _ in range(2)) + "\n"

    assert RULE not in {row["rule"] for row in scan_all("sample.md", text, {})}


def test_a_paragraph_of_one_sentence_is_not_an_ending_to_measure() -> None:
    assert prose_structure._ending_ratio([(1, SHORT_CLOSER)]) is None


def test_the_shipped_cuts_match_the_recorded_measurement() -> None:
    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    chosen = record["candidate_limits"]["95"]

    assert prose_structure.PUNCHY_ENDING_RATIO == record["punchy_ratio_cut"]
    assert prose_structure.PUNCHY_SHARE_LIMIT == chosen["share_limit"]


def test_the_record_states_the_human_cost_of_the_shipped_cut() -> None:
    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    rates = record["candidate_limits"]["95"]["by_origin"]

    assert rates["human"]["rate"] < 0.05
    assert rates["human"]["documents"] > 1000
