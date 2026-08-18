from argparse import Namespace

import pytest
from lib import bm25, review


def test_document_with_query_terms_ranks_first() -> None:
    documents = [
        {"text": "alpha beta beta", "path": "best", "corpus": "code"},
        {"text": "alpha gamma", "path": "other", "corpus": "code"},
    ]

    ranked = bm25.rank("alpha beta", documents)

    assert [row["path"] for row in ranked] == ["best", "other"]


def test_term_in_every_document_keeps_positive_idf() -> None:
    documents = [
        {"text": "shared", "path": "one", "corpus": "code"},
        {"text": "shared", "path": "two", "corpus": "code"},
    ]

    ranked = bm25.rank("shared", documents)

    assert len(ranked) == 2
    assert all(row["score"] > 0 for row in ranked)


def test_chunks_keep_eighty_line_boundaries() -> None:
    text = "\n".join(f"line {number}" for number in range(1, 166))

    documents = bm25.chunks("sample.py", text, bm25.CHUNK_LINES)

    assert [row["line"] for row in documents] == [1, 81, 161]
    assert len(documents[0]["text"].splitlines()) == 80
    assert len(documents[-1]["text"].splitlines()) == 5


def test_empty_documents_and_invalid_chunk_size_are_safe() -> None:
    assert bm25.rank("query", []) == []
    assert bm25.rank("query", [{"text": "", "path": "empty"}]) == []

    with pytest.raises(ValueError, match="positive"):
        bm25.chunks("sample.py", "text", 0)


def test_planted_source_chunk_wins_scope_integration(tmp_path) -> None:
    source = tmp_path / "source.py"
    lines = [f"plain line {number}" for number in range(1, 161)]
    lines[99] = "scope resolver keeps changed revision context"
    source.write_text("\n".join(lines), encoding="utf-8")
    args = Namespace(paths=["source.py"], commits=None, cwd=tmp_path)

    ranked = bm25.rank("changed revision context", review.code_documents(args))

    assert ranked[0]["path"] == "source.py"
    assert ranked[0]["line"] == 81
