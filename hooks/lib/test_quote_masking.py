import pytest

from lib.scanner import scan_all
from lib.markup import mask_phrase_mentions, mask_quoted

EM_DASH = chr(0x2014)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            '"It is important to note that we leverage robust synergies. I hope this helps!"',
            id="whole-quoted-line",
        ),
        pytest.param(
            '{"message": "It is important to note that we leverage robust synergies. I hope this helps!"}',
            id="json-string-in-markdown",
        ),
        pytest.param(
            'Note: "It is important to note that we leverage robust synergies. I hope this helps!"',
            id="labelled-quotation",
        ),
        pytest.param(
            '“It is important to note that we leverage robust synergies. I hope this helps!”',
            id="curly-quoted-line",
        ),
        pytest.param(
            'The speaker says "It is important to note that we leverage robust synergies. '
            'I hope this helps!" in the transcript.',
            id="speaker-quotes-full-sentences",
        ),
    ],
)
def test_quoting_a_full_sentence_does_not_hide_formulaic_filler(text: str) -> None:
    assert "formulaic_filler" in _rules(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("It is important to note the checksum excludes the trailing newline.", id="important-note"),
        pytest.param("  It is important to note the checksum excludes the trailing newline.", id="indented-note"),
        pytest.param("It is essential to remember the checksum.", id="essential-remember"),
    ],
)
def test_formulaic_filler_has_no_duplicate_weak_starter_finding(text: str) -> None:
    rules = _rules(text)

    assert "formulaic_filler" in rules
    assert "weak_sentence_starter" not in rules


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("It is important to check the checksum before upload.", id="important-check-upload"),
        pytest.param("It is important to check the checksum before decoding the packet.", id="important-check-packet"),
        pytest.param("It is essential to check the checksum.", id="essential-check"),
        pytest.param("It is necessary to note the checksum.", id="necessary-note"),
    ],
)
def test_independent_weak_starters_still_report(text: str) -> None:
    assert "weak_sentence_starter" in _rules(text)


def test_a_later_filler_does_not_hide_an_independent_sentence_starter() -> None:
    rules = _rules("What changes when it is essential to note the checksum?")

    assert {"weak_sentence_starter", "formulaic_filler"} <= rules


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        pytest.param(
            "The phrase “make no mistake” appears in this parser fixture.",
            "emphasis_crutch", id="named-curly-mention",
        ),
        pytest.param(
            'This is called "make no mistake" in the parser fixture.',
            "emphasis_crutch", id="called-straight-mention",
        ),
        pytest.param(
            "The code comment says “I promise” because that exact phrase is part of a parser fixture.",
            "performative_emphasis", id="comment-quoted-mention",
        ),
        pytest.param(
            "In the transcript, the speaker says “they exist, I promise” while describing the objects.",
            "performative_emphasis", id="speaker-short-mention",
        ),
    ],
)
def test_short_named_or_spoken_mentions_do_not_report_the_mentioned_phrase(text: str, rule: str) -> None:
    assert rule not in _rules(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('"make no mistake"', id="whole-line"),
        pytest.param('Note: "make no mistake"', id="labelled-line"),
    ],
)
def test_a_short_quote_without_mention_context_still_reports(text: str) -> None:
    assert "emphasis_crutch" in _rules(text)


def test_phrase_mention_mask_preserves_offsets_and_delimiters() -> None:
    text = "The phrase “make no mistake” appears here.\n"

    masked = mask_phrase_mentions(text)

    assert masked == "The phrase “               ” appears here.\n"
    assert len(masked) == len(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('"make no mistake"\n', id="whole-quoted-line"),
        pytest.param('The speaker says "Make no mistake. I promise." today.\n', id="quoted-sentences"),
    ],
)
def test_phrase_mention_mask_keeps_full_quoted_lines_and_sentences(text: str) -> None:
    assert mask_phrase_mentions(text) == text


def _rules(text: str) -> set[str]:
    return {row["rule"] for row in scan_all("notes.md", text + "\n", {})}


def test_structure_rules_skip_quoted_text() -> None:
    assert "narrator_distance" not in _rules('The survey quoted "some people believe the cache is slow" verbatim.')


def test_structure_rules_still_see_unquoted_text() -> None:
    assert "narrator_distance" in _rules("Some people believe the cache is slow.")


def test_punctuation_rules_skip_quoted_text() -> None:
    rules = _rules(f'The error text reads "retry{EM_DASH}later; or not" in the log.')
    assert "banned_dash" not in rules
    assert "prose_semicolon" not in rules


def test_punctuation_rules_still_see_unquoted_text() -> None:
    assert "prose_semicolon" in _rules("The cache is warm; the index is cold.")


def test_contractions_do_not_open_a_quote() -> None:
    assert "prose_semicolon" in _rules("Don't warm it; it's cold.")


def test_mask_keeps_length_and_delimiters() -> None:
    text = "Say 'hello there' and \"bye now\" please."
    masked = mask_quoted(text)
    assert len(masked) == len(text)
    assert "hello" not in masked
    assert "bye" not in masked
    assert masked.count('"') == 2
