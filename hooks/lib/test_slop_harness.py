import pytest

from lib.corpus_gate import requires_corpora
from lib.slop_harness import (
    Counts,
    Measurement,
    MetricFloor,
    PartitionedMeasurement,
    RuleScope,
    Surface,
    Unmeasurable,
    assert_floors,
    floor_regressions,
    format_partition_table,
    format_table,
    held_out_measurement,
    load_corpus,
    score_rule,
    score_rule_partitions,
    split_corpus,
)

pytestmark = requires_corpora


def test_corpus_split_is_deterministic_and_stratified() -> None:
    rows = load_corpus(RuleScope.LINE)
    first = split_corpus(rows)
    second = split_corpus(rows)

    assert first == second
    assert len(first.development) + len(first.held_out) == len(rows)
    for label in ("ai", "human"):
        development_count = sum(row.label == label for row in first.development)
        held_out_count = sum(row.label == label for row in first.held_out)
        assert abs(development_count - held_out_count) <= 1


def test_harness_reports_distinct_surface_capabilities() -> None:
    results = score_rule("empty_intensifier", RuleScope.LINE, tuple(Surface))

    prose, comment, commit = results
    assert isinstance(prose, Measurement)
    assert prose.surface == Surface.PROSE
    assert prose.counts.sample_size == len(load_corpus(RuleScope.LINE))
    assert prose.counts.true_positive >= MetricFloor(0.0, 0.0).minimum_true_positives
    assert isinstance(comment, Unmeasurable)
    assert "English rules do not run for code comments" in comment.reason
    assert isinstance(commit, Unmeasurable)
    assert "no distinct commit surface measurement" in commit.reason


def test_partitioned_document_score_reports_development_and_held_out_data() -> None:
    result, = score_rule_partitions(
        "weighted_slop_marker", RuleScope.DOCUMENT, (Surface.PROSE,)
    )

    assert isinstance(result, PartitionedMeasurement)
    held_out = held_out_measurement(result)
    assert held_out.counts == result.held_out
    assert held_out.corpus == result.corpus
    assert result.development.sample_size + held_out.counts.sample_size == len(
        load_corpus(RuleScope.DOCUMENT)
    )
    with pytest.raises(TypeError, match="pass held_out_measurement"):
        floor_regressions((result,), {Surface.PROSE: MetricFloor(0.0, 0.0)})
    table = format_partition_table((result,))
    assert "development/in-sample" in table
    assert "held-out" in table
    assert result.corpus in table
    assert result.bias in table


def test_table_keeps_denominators_sample_size_and_bias_with_each_metric() -> None:
    result = Measurement(
        "sample_rule",
        Surface.PROSE,
        "sample.jsonl",
        "Narrow sample bias.",
        Counts(3, 1, 2, 4),
    )

    table = format_table((result,))

    assert "3/5 AI (n=10)" in table
    assert "0.7500 (3/4, n=10)" in table
    assert "0.6000 (3/5, n=10)" in table
    assert "Narrow sample bias." in table


def test_unknown_rule_and_scope_mismatch_raise_actionable_errors() -> None:
    with pytest.raises(ValueError, match="not emitted by scanner.scan_all"):
        score_rule("no_such_rule_at_all", RuleScope.LINE, (Surface.PROSE,))
    with pytest.raises(ValueError, match="requires 'document' scope"):
        score_rule("weighted_slop_marker", RuleScope.LINE, (Surface.PROSE,))


def test_punctuation_rule_is_registered_for_line_measurement() -> None:
    result, = score_rule("banned_dash", RuleScope.LINE, (Surface.PROSE,))

    assert isinstance(result, Measurement)


def test_floor_checks_require_every_surface() -> None:
    supported = Measurement(
        "sample_rule", Surface.PROSE, "sample.jsonl", "Narrow sample bias.", Counts(8, 2, 2, 8)
    )
    unsupported = Unmeasurable(
        "sample_rule", Surface.COMMENT, "sample.jsonl", "Narrow sample bias.", 20,
        "Scanner cannot invoke this rule on comments.",
    )

    assert floor_regressions((supported,), {}) == (
        "sample_rule on prose has no recorded floor",
    )
    assert floor_regressions(
        (unsupported,), {Surface.COMMENT: MetricFloor(0.0, 0.0)}
    ) == (
        "sample_rule on comment is unmeasurable: Scanner cannot invoke this rule on comments.",
    )


def test_floor_checks_require_true_positive_evidence() -> None:
    result = Measurement(
        "sample_rule", Surface.COMMIT, "sample.jsonl", "Narrow sample bias.", Counts(0, 0, 8, 8)
    )

    regressions = floor_regressions(
        (result,), {Surface.COMMIT: MetricFloor(0.0, 0.0)}
    )
    assert "sample_rule on commit has no true positives" in regressions


def test_floor_checks_fail_only_for_regressions() -> None:
    result = Measurement(
        "sample_rule", Surface.PROSE, "sample.jsonl", "Narrow sample bias.", Counts(8, 2, 2, 8)
    )

    assert_floors((result,), {Surface.PROSE: MetricFloor(0.8, 0.8)})
    with pytest.raises(AssertionError, match="precision is below 0.9000"):
        assert_floors((result,), {Surface.PROSE: MetricFloor(0.9, 0.8)})
