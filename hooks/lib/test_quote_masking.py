from lib.scanner import scan_all
from lib.slop_structure import mask_quoted

EM_DASH = chr(0x2014)


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
