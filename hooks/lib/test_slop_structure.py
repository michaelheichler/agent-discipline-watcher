from lib.prose_structure import _markdown_prose_lines
from lib.slop_structure import (
    OMITTED_STRUCTURE_RULES,
    STRUCTURE_CANDIDATES,
    STRUCTURE_RULES,
    _PASSIVE_VOICE_RE,
)

IRREGULAR_PASSIVES = (
    "The index was built overnight.",
    "The report was sent to the reviewers.",
    "The lock was kept until the batch finished.",
    "Two commits were lost in the rebase.",
    "We were told the queue had drained.",
    "The regression was caught by the smoke test.",
    "The cap is set to forty words.",
    "The manifest is read at startup.",
    "The lease is held by another session.",
    "The cache was rebuilt after the deploy.",
)
ACTIVE_CONTROLS = (
    "The job builds the index overnight.",
    "The reviewer read the manifest at startup.",
    "We lost two commits in the rebase.",
    "The scanner is fast and the reporter is slower.",
    "The result is a clean report.",
    "The lease was for a single session.",
)


CORPUS_EXAMPLES = (
    ("binary_contrast", "Speed isn't the problem. Locking is."),
    ("formulaic_construction", "By the time we shipped, I was tired."),
    ("false_agency", "The market rewards speed."),
    ("narrator_distance", "Some people believe technology isolates us."),
    ("passive_voice", "Regulations were being followed."),
    ("rhetorical_setup", "Have you ever wondered what lies beyond our galaxy?"),
    ("negative_listing", "It wasn't the disk. It wasn't the network. It was the lock."),
    ("dramatic_fragmentation", "Locking. That's it. That's the bug."),
    ("weak_sentence_starter", "Look, the lock is held too long."),
    ("lazy_extreme", "Nobody ever reads the changelog."),
)


def test_candidate_patterns_are_general_not_corpus_phrases() -> None:
    candidates = {candidate.name: candidate for candidate in STRUCTURE_CANDIDATES}

    for rule_name, text in CORPUS_EXAMPLES:
        assert candidates[rule_name].pattern.search(text)


def test_structure_candidates_are_shipped_or_omitted() -> None:
    candidate_names = {candidate.name for candidate in STRUCTURE_CANDIDATES}
    shipped_names = {rule.name for rule in STRUCTURE_RULES}
    omitted_names = set(OMITTED_STRUCTURE_RULES)
    omitted_candidates = candidate_names - shipped_names

    assert shipped_names.isdisjoint(omitted_names)
    assert omitted_candidates <= omitted_names


def test_structure_candidates_use_the_markdown_prose_contract() -> None:
    examples = dict(CORPUS_EXAMPLES)
    fenced_lines = tuple(examples.values())
    table_lines = tuple(f"| {text} |" for text in examples.values())
    quote_lines = tuple(f"> {text}" for text in examples.values())
    text = "\n".join(
        (
            "```text",
            *fenced_lines,
            "```",
            "| Detail |",
            "| --- |",
            *table_lines,
            *quote_lines,
        )
    )
    prose_lines = tuple(_markdown_prose_lines(text))

    for candidate in STRUCTURE_CANDIDATES:
        assert candidate.pattern.search(examples[candidate.name])
        assert all(not candidate.pattern.search(line) for _number, line in prose_lines)


def test_passive_voice_catches_irregular_participles() -> None:
    assert all(_PASSIVE_VOICE_RE.search(text) for text in IRREGULAR_PASSIVES)


def test_passive_voice_leaves_active_sentences_alone() -> None:
    assert all(not _PASSIVE_VOICE_RE.search(text) for text in ACTIVE_CONTROLS)


def test_omitted_categories_record_their_measurement_reason() -> None:
    shipped = {rule.name for rule in STRUCTURE_RULES}
    candidates = {candidate.name for candidate in STRUCTURE_CANDIDATES}
    assert candidates - shipped == set(OMITTED_STRUCTURE_RULES)
    assert all(reason.strip() for reason in OMITTED_STRUCTURE_RULES.values())
    assert all(
        "held-out" in reason or "Held-out" in reason
        for reason in OMITTED_STRUCTURE_RULES.values()
    )
