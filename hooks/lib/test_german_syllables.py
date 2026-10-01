"""Checked against spoken German, because a miscounted syllable shifts every readability score built on it."""
from __future__ import annotations

import pytest

from lib.german_syllables import count_syllables


@pytest.mark.parametrize(("word", "expected"), (
    ("Beispiel", 2),
    ("Schuh", 1),
    ("Freundschaft", 2),
    ("Tapeziertischoberfläche", 8),
    ("Automobilzuliefererkonferenz", 11),
))
def test_a_word_counts_its_spoken_syllables(word: str, expected: int) -> None:
    assert count_syllables(word) == expected


@pytest.mark.parametrize(("word", "expected"), (
    ("Quelle", 2),
    ("Quadrat", 2),
    ("Qualität", 3),
))
def test_the_u_after_q_is_not_a_syllable(word: str, expected: int) -> None:
    assert count_syllables(word) == expected


@pytest.mark.parametrize(("word", "expected"), (
    ("Idee", 2),
    ("Saal", 1),
))
def test_a_doubled_vowel_is_one_long_syllable(word: str, expected: int) -> None:
    assert count_syllables(word) == expected


@pytest.mark.parametrize(("word", "expected"), (
    ("mein", 1),
    ("Liebe", 2),
    ("Haus", 1),
    ("Maus", 1),
    ("Baum", 1),
    ("Freund", 1),
    ("Bäume", 2),
), ids=("ei", "ie", "au-haus", "au-maus", "au-baum", "eu", "äu"))
def test_a_diphthong_is_one_syllable(word: str, expected: int) -> None:
    assert count_syllables(word) == expected


@pytest.mark.parametrize(("word", "expected"), (
    ("Chaos", 2),
    ("Theater", 3),
))
def test_two_unlisted_adjacent_vowels_are_two_syllables(word: str, expected: int) -> None:
    assert count_syllables(word) == expected


@pytest.mark.parametrize("word", ("Pfft", "Hmm", "Psst"))
def test_a_word_without_vowels_still_counts_one_syllable(word: str) -> None:
    assert count_syllables(word) == 1


@pytest.mark.parametrize("text", ("", "123", "--"))
def test_input_without_letters_has_no_syllables(text: str) -> None:
    assert count_syllables(text) == 0
