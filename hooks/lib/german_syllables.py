"""Vowel-group counting, because a syllabifier needs no dictionary to approximate German well."""
from __future__ import annotations

import re

VOWELS = frozenset("aeiouäöüy")
# Merged since German fuses these five pairs in speech.
DIPHTHONGS = frozenset({"ei", "ie", "au", "eu", "äu"})
LETTER_RE = re.compile(r"[a-zäöüß]+", re.IGNORECASE)


def _is_merged_pair(first: str, second: str) -> bool:
    """German spells a long vowel by repeating the letter, because the double stands for one sustained sound."""
    return first + second in DIPHTHONGS or first == second


def count_syllables(word: str) -> int:
    """German defaults to hiatus for an unlisted vowel pair, because only a listed diphthong actually fuses in speech."""
    # Dropped, since "qu" spells one consonant sound, not a vowel.
    normalized = word.lower().replace("qu", "q")
    letters = list("".join(LETTER_RE.findall(normalized)))
    count = 0
    index = 0
    total = len(letters)
    while index < total:
        if letters[index] not in VOWELS:
            index += 1
            continue
        count += 1
        if index + 1 < total and letters[index + 1] in VOWELS and _is_merged_pair(letters[index], letters[index + 1]):
            index += 2
        else:
            index += 1
    return max(count, 1) if letters else 0
