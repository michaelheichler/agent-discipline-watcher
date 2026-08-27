from lib.corpus_gate import requires_corpora
from lib.slop_harness import (
    Measurement,
    MetricFloor,
    PartitionedMeasurement,
    RuleScope,
    Surface,
    assert_floors,
    score_rule_partitions,
)
from lib.slop_phrase import (
    OMITTED_PHRASE_RULES,
    RULE_EVIDENCE,
    RULE_SCOPES,
    scan_slop_phrases,
)


def _rules_for(text: str) -> tuple[tuple[str, int], ...]:
    findings = scan_slop_phrases("sample.md", text, {})
    return tuple((finding["rule"], finding["line"]) for finding in findings)


def _dense_markers() -> str:
    return " ".join(("holistic", "synergy", "paradigm", *(["plain"] * 147)))


def test_density_requires_multiple_markers_and_cites_the_rate() -> None:
    quiet = " ".join(("thought-provoking", *(["plain"] * 149)))
    repeated = " ".join(("dynamic", "dynamic", "dynamic"))
    legacy = " ".join(("delve into detail", "delve into data", "delve into logs"))
    findings = scan_slop_phrases("sample.md", _dense_markers(), {})
    weighted = [row for row in findings if row["rule"] == "weighted_slop_marker"]

    assert "weighted_slop_marker" not in {rule for rule, _line in _rules_for(quiet)}
    assert "weighted_slop_marker" not in {rule for rule, _line in _rules_for(repeated)}
    assert "weighted_slop_marker" not in {rule for rule, _line in _rules_for(legacy)}
    assert len(weighted) == 3
    assert all("per 1,000 words" in row["detail"] for row in weighted)
    assert all("threshold" in row["detail"] for row in weighted)


def test_formulaic_categories_report_one_finding_per_phrase() -> None:
    text = "\n".join(
        (
            "In a world where teams adapt, evidence matters.",
            "Picture this: the build stays green.",
            "First and foremost, the measured result matters.",
            "Without a doubt, the sample changed.",
            "That means that the estimate failed.",
        )
    )

    assert _rules_for(text) == (
        ("formulaic_opener", 1),
        ("formulaic_opener", 2),
        ("formulaic_filler", 3),
        ("formulaic_filler", 4),
        ("formulaic_filler", 5),
    )


def test_multiline_and_unmatched_code_keep_phrase_line_coordinates() -> None:
    text = "\n".join(
        (
            "Set the `flag",
            "value` before running the job.",
            "Padding line one.",
            "Padding line two.",
            "Without a doubt, the measured result matters.",
            "A stray ` marker does not hide later prose.",
            "More padding.",
            "Without a doubt, the next measured result matters.",
        )
    )

    findings = scan_slop_phrases("sample.md", text, {})
    filler = [row for row in findings if row["rule"] == "formulaic_filler"]

    assert [row["line"] for row in filler] == [5, 8]
    assert all("Without a doubt" in row["snippet"] for row in filler)


def test_hidden_phrases_do_not_become_findings() -> None:
    text = "\n".join(
        (
            "```text",
            "It is important to note this hidden phrase.",
            "```",
            "`Without a doubt` is quoted code.",
            "<script>",
            "One thing is clear that this script stays hidden.",
            "</script>",
        )
    )

    assert _rules_for(text) == ()


def test_phrase_rules_are_measured_or_omitted() -> None:
    phrase_rules = {
        "weighted_slop_marker",
        "formulaic_opener",
        "formulaic_filler",
        "formulaic_closer_phrase",
    }
    measured_rules = set(RULE_SCOPES)
    omitted_rules = set(OMITTED_PHRASE_RULES)
    reason = OMITTED_PHRASE_RULES["formulaic_closer_phrase"]

    assert measured_rules.isdisjoint(omitted_rules)
    assert phrase_rules == measured_rules | omitted_rules
    assert "truncates endings" in reason


@requires_corpora
def test_rule_evidence_has_heldout_harness_floors() -> None:
    evidence_by_rule = dict(RULE_EVIDENCE)
    results = tuple(
        score_rule_partitions(rule, RuleScope(scope), (Surface.PROSE,))[0]
        for rule, scope in RULE_SCOPES.items()
    )

    for result in results:
        assert isinstance(result, PartitionedMeasurement)
        evidence = evidence_by_rule[result.rule]
        held_out = Measurement(
            result.rule,
            result.surface,
            result.corpus,
            result.bias,
            result.held_out,
        )
        assert held_out.counts.sample_size == evidence.sample_size
        assert held_out.counts.true_positive >= evidence.counts.true_positive
        assert_floors((held_out,), {Surface.PROSE: MetricFloor(0.9, 0.02)})
