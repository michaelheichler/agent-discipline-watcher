"""Rank review records and source chunks with a small Okapi BM25 index."""

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
TERM_SATURATION = 1.2
LENGTH_NORMALIZATION = 0.75


def tokenize(text: str) -> list[str]:
    """Normalize query and corpus words to comparable lowercase tokens."""
    return TOKEN_RE.findall(text.lower())


def chunks(path: str, text: str, size: int = 80) -> list[dict]:
    """Keep source context bounded so search results point to useful regions."""
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
    """Apply Okapi BM25 and keep equal scores in original corpus order."""
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


def _finding_documents(findings: list[dict]) -> list[dict]:
    return [
        {
            "text": f"{row['rule']} {row['excerpt']} {row['hint']}",
            "path": row["path"],
            "line": row["line"],
            "corpus": "finding",
        }
        for row in findings
    ]


def run_search(args) -> list[dict]:
    """Build only the requested corpora before ranking one query."""
    from . import review

    use_findings = args.findings or not args.code
    use_code = args.code or not args.findings
    documents = []
    if use_findings:
        findings, _, _, _ = review.run_review(args)
        documents.extend(_finding_documents(findings))
    if use_code:
        documents.extend(review.code_documents(args))
    return rank(args.query, documents)


def emit(args) -> int:
    """Print tagged search hits in descending relevance order."""
    for row in run_search(args):
        first_line = row["text"].splitlines()[0] if row["text"] else ""
        print(
            f"{row['score']:.3f}\t{row['corpus']}\t"
            f"{row['path']}:{row.get('line', 1)}\t{first_line}"
        )
    return 0
