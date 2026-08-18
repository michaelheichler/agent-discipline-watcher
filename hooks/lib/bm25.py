"""BM25 is implemented directly here so that ranking review search results does not require an external search-index dependency."""

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
TERM_SATURATION = 1.2
LENGTH_NORMALIZATION = 0.75
CHUNK_LINES = 80


def tokenize(text: str) -> list[str]:
    """Lowercased so that a query token matches source text no matter what casing the source used when it was written."""
    return TOKEN_RE.findall(text.lower())


def chunks(path: str, text: str, size: int) -> list[dict]:
    """Windowed into fixed-size chunks so that a search hit points at a useful region instead of an entire file."""
    if size < 1:
        raise ValueError("chunk size must be positive")
    lines = text.splitlines()
    return [
        {
            "path": path,
            "line": start + 1,
            "text": "\n".join(lines[start : start + size]),
            "corpus": "code",
        }
        for start in range(0, len(lines), size)
    ]


def _score(terms: list[str], words: list[str], corpus: tuple) -> float:
    frequencies, total, average = corpus
    counts = Counter(words)
    score = 0.0
    for term in terms:
        frequency = counts[term]
        if not frequency:
            continue
        document_frequency = frequencies[term]
        inverse = math.log(
            (total - document_frequency + 0.5) / (document_frequency + 0.5) + 1
        )
        normalizer = frequency + TERM_SATURATION * (
            1 - LENGTH_NORMALIZATION + LENGTH_NORMALIZATION * len(words) / average
        )
        score += inverse * frequency * (TERM_SATURATION + 1) / normalizer
    return score


def rank(query: str, documents: list[dict]) -> list[dict]:
    """Ties keep the original corpus order because a stable sort avoids nondeterministic search results across runs."""
    terms = tokenize(query)
    tokenized = [tokenize(item.get("text", "")) for item in documents]
    total = len(documents)
    average = sum(map(len, tokenized)) / total if total else 1.0
    average = average or 1.0
    frequencies = Counter(term for words in tokenized for term in set(words))
    corpus = (frequencies, total, average)
    scored = [
        (_score(terms, words, corpus), index)
        for index, words in enumerate(tokenized)
    ]
    matches = ((score, index) for score, index in scored if score > 0)
    return [
        documents[index] | {"score": score}
        for score, index in sorted(matches, key=lambda item: (-item[0], item[1]))
    ]
