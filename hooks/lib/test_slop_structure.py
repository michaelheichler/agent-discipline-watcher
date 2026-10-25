import pytest

from lib.prose_structure import _markdown_prose_lines
from lib.scanner import scan_all
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


@pytest.mark.parametrize(("rule_name", "text"), [pytest.param(*example, id=example[0]) for example in CORPUS_EXAMPLES])
def test_candidate_patterns_are_general_not_corpus_phrases(rule_name: str, text: str) -> None:
    candidates = {candidate.name: candidate for candidate in STRUCTURE_CANDIDATES}

    assert candidates[rule_name].pattern.search(text)


def test_structure_candidates_are_shipped_or_omitted() -> None:
    candidate_names = {candidate.name for candidate in STRUCTURE_CANDIDATES}
    shipped_names = {rule.name for rule in STRUCTURE_RULES}
    omitted_names = set(OMITTED_STRUCTURE_RULES)
    omitted_candidates = candidate_names - shipped_names

    assert shipped_names.isdisjoint(omitted_names)
    assert omitted_candidates <= omitted_names


def _masked_example_lines() -> tuple[tuple[int, str], ...]:
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
    return tuple(_markdown_prose_lines(text))


@pytest.mark.parametrize("candidate", [pytest.param(candidate, id=candidate.name) for candidate in STRUCTURE_CANDIDATES])
def test_structure_candidates_use_the_markdown_prose_contract(candidate) -> None:
    prose_lines = _masked_example_lines()

    assert candidate.pattern.search(dict(CORPUS_EXAMPLES)[candidate.name])
    assert [line for _number, line in prose_lines if candidate.pattern.search(line)] == []


def test_passive_voice_catches_irregular_participles() -> None:
    assert all(_PASSIVE_VOICE_RE.search(text) for text in IRREGULAR_PASSIVES)


def test_passive_voice_leaves_active_sentences_alone() -> None:
    assert all(not _PASSIVE_VOICE_RE.search(text) for text in ACTIVE_CONTROLS)


def test_passive_voice_leaves_read_only_prose_alone() -> None:
    prose = (
        "Both caches are read-only in safe mode.",
        "The mounted volumes are read only until the lock clears.",
    )
    assert all(not _PASSIVE_VOICE_RE.search(text) for text in prose)


def _passive_lines(sentence: str) -> list[int]:
    rows = scan_all("doc.md", f"Intro line here.\n\n{sentence}\n", {"prose_languages": ["en"]})
    return [row["line"] for row in rows if row["rule"] == "passive_voice"]


@pytest.mark.parametrize("sentence", [
    pytest.param("Its shelf is open.", id="open"),
    pytest.param("The fix is often slow.", id="often"),
    pytest.param("The plan is even simpler.", id="even"),
    pytest.param("The light is green.", id="green"),
    pytest.param("The light was red.", id="red"),
    pytest.param("The gap is between two halls.", id="between"),
])
def test_an_adjective_ending_in_ed_or_en_after_a_form_of_be_is_no_passive(sentence: str) -> None:
    assert _passive_lines(sentence) == []


@pytest.mark.parametrize("sentence", [
    pytest.param("The shelf was opened.", id="opened"),
    pytest.param("The tears were shed.", id="shed"),
    pytest.param("The rooms were needed.", id="needed"),
    pytest.param("The data was screened.", id="screened"),
])
def test_a_participle_built_on_an_excluded_word_still_reports_a_passive(sentence: str) -> None:
    assert _passive_lines(sentence) == [3]


def test_omitted_categories_record_their_measurement_reason() -> None:
    shipped = {rule.name for rule in STRUCTURE_RULES}
    candidates = {candidate.name for candidate in STRUCTURE_CANDIDATES}
    assert candidates - shipped == set(OMITTED_STRUCTURE_RULES)
    assert all(reason.strip() for reason in OMITTED_STRUCTURE_RULES.values())
    assert all(
        "held-out" in reason or "Held-out" in reason
        for reason in OMITTED_STRUCTURE_RULES.values()
    )
