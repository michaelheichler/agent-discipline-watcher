"""Expected scores are worked by hand from the published formulas, because a pinned float would hide which count went wrong."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from lib.german_readability import lix, sentences, wiener_sachtextformel_1, words

TWO_SENTENCES = "Der Hund lief schnell. Die Katze schlief lange auf dem warmen Sofa."
LONG_SYLLABLE_SENTENCE = "Die Qualität der Theater bleibt hoch."


@dataclass(frozen=True)
class HandCountedText:
    three_syllable_share: float
    words_per_sentence: float
    long_letter_share: float
    one_syllable_share: float

    def published_wstf1(self) -> float:
        return (
            0.1935 * self.three_syllable_share
            + 0.1672 * self.words_per_sentence
            + 0.1297 * self.long_letter_share
            - 0.0327 * self.one_syllable_share
            - 0.875
        )


def test_sentences_split_at_a_mark_before_a_capital() -> None:
    assert sentences(TWO_SENTENCES) == ["Der Hund lief schnell.", "Die Katze schlief lange auf dem warmen Sofa."]


def test_a_lowercase_word_after_an_abbreviation_keeps_the_sentence_whole() -> None:
    assert sentences("Er kam um fünf bzw. etwas später. Dann ging er.") == [
        "Er kam um fünf bzw. etwas später.",
        "Dann ging er.",
    ]


def test_words_keep_letters_and_drop_punctuation() -> None:
    assert words(TWO_SENTENCES) == [
        "Der", "Hund", "lief", "schnell", "Die", "Katze", "schlief", "lange", "auf", "dem", "warmen", "Sofa",
    ]


def test_words_keep_umlauts_and_sharp_s_inside_a_word() -> None:
    assert words("Größe, Maß und Übel!") == ["Größe", "Maß", "und", "Übel"]


def test_lix_adds_sentence_length_to_the_share_of_words_past_six_letters() -> None:
    word_count = 12
    sentence_count = 2
    words_past_six_letters = ("schnell", "schlief")

    expected = word_count / sentence_count + 100 * len(words_past_six_letters) / word_count

    assert lix(TWO_SENTENCES) == pytest.approx(expected)


@pytest.mark.parametrize(("text", "hand_counted"), (
    pytest.param(
        TWO_SENTENCES,
        HandCountedText(
            three_syllable_share=100 * 0 / 12,
            words_per_sentence=12 / 2,
            long_letter_share=100 * 2 / 12,
            one_syllable_share=100 * 8 / 12,
        ),
        id="no-word-reaches-three-syllables",
    ),
    pytest.param(
        LONG_SYLLABLE_SENTENCE,
        HandCountedText(
            three_syllable_share=100 * 2 / 6,
            words_per_sentence=6 / 1,
            long_letter_share=100 * 2 / 6,
            one_syllable_share=100 * 4 / 6,
        ),
        id="qualitaet-and-theater-reach-three-syllables",
    ),
))
def test_wiener_sachtextformel_weighs_the_four_measured_shares(text: str, hand_counted: HandCountedText) -> None:
    assert wiener_sachtextformel_1(text) == pytest.approx(hand_counted.published_wstf1())


@pytest.mark.parametrize("score", (lix, wiener_sachtextformel_1))
@pytest.mark.parametrize("text", ("", "... !"))
def test_text_without_words_scores_zero(score: Callable[[str], float], text: str) -> None:
    assert score(text) == 0.0
