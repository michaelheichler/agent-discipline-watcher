from lib.corpus_gate import requires_corpora
from lib.prose_structure import RHYTHM_LIMITATIONS
from lib.scanner import scan_all
from lib.slop_harness import (
    PartitionedMeasurement,
    RuleScope,
    Surface,
    held_out_measurement,
    score_rule_partitions,
)


def _findings(text: str) -> list[dict]:
    return scan_all("sample.md", text, {})


def test_low_sentence_variance_fires_below_the_threshold() -> None:
    uniform = (
        "Cats watch birds. Dogs chase balls. Fish swim slowly. Bees gather pollen."
    )
    varied = (
        "Run. The dog runs home. "
        "This longer sentence carries several more words across the empty field. "
        "A final sentence has enough words to keep the rhythm from becoming predictable."
    )

    assert "low_sentence_variance" in {row["rule"] for row in _findings(uniform)}
    assert "low_sentence_variance" not in {row["rule"] for row in _findings(varied)}


def test_low_variance_finding_points_to_its_paragraph() -> None:
    text = (
        "A varied opening stands alone.\n\n"
        "Cats watch birds.\n"
        "Dogs chase balls. Fish swim slowly. Bees gather pollen.\n"
    )

    rows = [
        row for row in _findings(text)
        if row["rule"] == "low_sentence_variance"
    ]

    assert len(rows) == 1
    assert rows[0]["line"] == 3


def test_three_item_rule_uses_lists_not_clauses() -> None:
    inline = "The plan covers speed, cost, and quality."
    markdown = "- speed\n- cost\n- quality\n"
    four_items = "- speed\n- cost\n- quality\n- scope\n"
    nested = "- speed\n  - cost\n  - quality\n"
    loose = "- speed\n\n- cost\n\n- quality\n"
    appositive = "The scanner, which is fast, and the reporter both run."
    subordinate = "Because it failed, we retried, and the run passed."
    trailing_clause = "We weighed speed, cost, and quality against the budget."

    assert "three_item_list" in {row["rule"] for row in _findings(inline)}
    assert "three_item_list" in {row["rule"] for row in _findings(markdown)}
    assert "three_item_list" not in {row["rule"] for row in _findings(four_items)}
    assert "three_item_list" not in {row["rule"] for row in _findings(nested)}
    assert "three_item_list" in {row["rule"] for row in _findings(loose)}
    assert "three_item_list" not in {row["rule"] for row in _findings(appositive)}
    assert "three_item_list" not in {row["rule"] for row in _findings(subordinate)}
    assert "three_item_list" not in {row["rule"] for row in _findings(trailing_clause)}


def test_rhythm_rules_inherit_markdown_masking() -> None:
    uniform = "Cats watch birds. Dogs chase balls. Fish swim slowly. Bees gather pollen."
    text = (
        "```\n"
        f"{uniform}\n"
        "- speed\n- cost\n- quality\n"
        "```\n"
        "| Heading | Detail |\n"
        "| --- | --- |\n"
        f"| {uniform} | speed, cost, and quality |\n"
        "[source]: speed, cost, and quality\n"
    )

    rules = {row["rule"] for row in _findings(text)}

    assert "low_sentence_variance" not in rules
    assert "three_item_list" not in rules


def test_frontmatter_does_not_create_unanchored_three_item_findings() -> None:
    text = "---\ntags: speed, cost, and quality\n---\nPlain prose.\n"

    assert "three_item_list" not in {row["rule"] for row in _findings(text)}


@requires_corpora
def test_variance_keeps_heldout_document_measurement_floors() -> None:
    partitioned, = score_rule_partitions(
        "low_sentence_variance",
        RuleScope.DOCUMENT,
        (Surface.PROSE,),
    )

    assert isinstance(partitioned, PartitionedMeasurement)
    held_out = held_out_measurement(partitioned)
    assert held_out.counts.false_positive == 0
    assert RHYTHM_LIMITATIONS["low_sentence_variance"]


def test_unmeasured_rhythm_categories_record_their_reason() -> None:
    assert "uniform_paragraph_endings" not in RHYTHM_LIMITATIONS
    assert "no true positive" in RHYTHM_LIMITATIONS["low_sentence_variance"]
