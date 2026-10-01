"""Pinned by behavior, because a wrong verdict would hold German text to English rules."""
from __future__ import annotations

from lib.prose_language import allowed_languages, paragraph_languages, paragraph_signal

GERMAN = (
    "Der Bericht zeigt, dass die Messung auf dem deutschen Korpus noch nicht abgeschlossen ist "
    "und wir die Schwelle deshalb erst später festlegen."
)
ENGLISH = (
    "The report shows that the measurement on the German corpus is not finished yet, "
    "so we set the threshold only after it is in."
)


def _languages(text: str, allowed: tuple[str, ...] = ("en", "de")) -> list[tuple[str, bool]]:
    return [(row.language, row.weak) for row in paragraph_languages(text, allowed)]


def test_a_german_and_an_english_paragraph_in_one_file_keep_their_own_language() -> None:
    assert _languages(f"{GERMAN}\n\n{ENGLISH}\n") == [("de", False), ("en", False)]


def test_english_alone_sends_every_paragraph_to_the_english_rules() -> None:
    assert _languages(f"{GERMAN}\n\n{ENGLISH}\n", ("en",)) == [("en", False), ("en", False)]


def test_a_short_paragraph_takes_the_document_language_and_is_marked_weak() -> None:
    text = f"{GERMAN}\n\nDanke dir.\n\n{GERMAN}\n"

    assert _languages(text)[1] == ("de", True)


def test_a_document_without_a_strong_paragraph_falls_back_to_english() -> None:
    assert _languages("Danke dir.\n\nBis bald.\n") == [("en", True), ("en", True)]


def test_a_fenced_code_block_is_not_a_paragraph() -> None:
    text = f"{GERMAN}\n```\nthe value is set when the loop has run for each of them\n```\n"

    assert _languages(text) == [("de", False)]


def test_inline_code_paths_and_urls_do_not_outvote_the_prose() -> None:
    text = (
        "Die Datei `if the value is not set then return it` liegt unter docs/the/and/of.md "
        "und https://example.com/the/and/is/for erklärt, wie sie gebaut wird."
    )

    assert paragraph_signal(text).language == "de"


def test_umlauts_decide_a_paragraph_without_stop_words() -> None:
    assert paragraph_signal("Größere Änderungen bleiben möglich.").language == "de"


def test_a_paragraph_with_no_signal_has_no_language() -> None:
    assert paragraph_signal("Release 0.24.1 ready.").language is None


def test_the_policy_can_switch_german_off() -> None:
    assert allowed_languages({"prose_languages": ["en"]}) == ("en",)


def test_a_malformed_policy_keeps_both_languages() -> None:
    assert allowed_languages({"prose_languages": "en"}) == ("en", "de")
