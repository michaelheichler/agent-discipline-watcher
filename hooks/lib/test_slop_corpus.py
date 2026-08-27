import csv
import importlib.util
import json

from lib.corpus_gate import requires_corpora

pytestmark = requires_corpora
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import TypedDict, cast


class CorpusRow(TypedDict):
    label: str
    source: str
    bias: str
    text: str


CORPUS_DIRECTORY = Path(__file__).parent
BUILDER_PATH = CORPUS_DIRECTORY.parents[1] / "evals" / "build_slop_corpora.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_slop_corpora", BUILDER_PATH)
    if spec is None:
        raise ImportError(f"Cannot create an import specification for {BUILDER_PATH}")
    if spec.loader is None:
        raise ImportError(f"Import specification for {BUILDER_PATH} has no loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_slop_corpora = _load_builder()
EXPECTED_COUNTS = {
    build_slop_corpora.SENTENCE_OUTPUT_NAME: {"ai": 648, "human": 651},
    build_slop_corpora.DOCUMENT_OUTPUT_NAME: {"ai": 41, "human": 41},
}
EXPECTED_SOURCES = {
    build_slop_corpora.SENTENCE_OUTPUT_NAME: build_slop_corpora.SENTENCE_SOURCE_NAME,
    build_slop_corpora.DOCUMENT_OUTPUT_NAME: build_slop_corpora.DOCUMENT_SOURCE_NAME,
}
EXPECTED_BIASES = {
    build_slop_corpora.SENTENCE_OUTPUT_NAME: build_slop_corpora.SENTENCE_BIAS,
    build_slop_corpora.DOCUMENT_OUTPUT_NAME: (
        build_slop_corpora.DOCUMENT_BIAS + " " + build_slop_corpora.DOCUMENT_TRUNCATION_NOTE
    ),
}
CsvValues = tuple[str, ...]
CsvRows = tuple[CsvValues, ...]


def _load_corpus(path: Path) -> list[CorpusRow]:
    rows: list[CorpusRow] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = json.loads(line)
        assert isinstance(parsed, dict), (path, line_number)
        assert set(parsed) == {"label", "source", "bias", "text"}, (path, line_number)
        assert all(isinstance(parsed[field], str) for field in parsed), (path, line_number)
        rows.append(cast(CorpusRow, parsed))
    return rows


def _words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _write_csv(path: Path, fieldnames: CsvValues, rows: CsvRows) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fieldnames)
        writer.writerows(rows)


def _write_sources(
    directory: Path, sentence_rows: CsvRows, document_rows: CsvRows
) -> None:
    directory.mkdir()
    _write_csv(
        directory / build_slop_corpora.SENTENCE_SOURCE_NAME,
        ("id", "text", "label", "ignored"),
        sentence_rows,
    )
    _write_csv(
        directory / build_slop_corpora.DOCUMENT_SOURCE_NAME,
        ("text", "generated"),
        document_rows,
    )
    for source_name in build_slop_corpora.REJECTED_SOURCE_NAMES:
        (directory / source_name).write_text("not accepted source data\n", encoding="utf-8")


def test_committed_corpora_are_canonical_and_balanced() -> None:
    for output_name, expected_counts in EXPECTED_COUNTS.items():
        path = CORPUS_DIRECTORY / output_name
        rows = _load_corpus(path)
        counts = Counter(row["label"] for row in rows)
        assert counts == expected_counts
        assert max(counts.values()) / len(rows) <= 0.60
        assert {row["source"] for row in rows} == {EXPECTED_SOURCES[output_name]}
        assert {row["bias"] for row in rows} == {EXPECTED_BIASES[output_name]}
        assert path.read_text(encoding="utf-8") == build_slop_corpora.serialize_corpus(rows)


def _sentence_fixture_rows() -> CsvRows:
    return (
        ("1", "A short sentence from a human writer.", "human", "x"),
        ("2", "An AI sentence used for this corpus.", "ai", "x"),
        ("3", "A second human sentence for balance.", "human", "x"),
        ("4", "Another AI sentence used for balance.", "ai", "x"),
    )


def _document_fixture_rows() -> CsvRows:
    """Spans the truncation floor on both sides, because the bug this replaces kept short AI rows against long human ones."""
    return (
        (_words("ai-short-", 160), "1"),
        (_words("ai-mid-", 240), "1"),
        (_words("ai-high-", 300), "1"),
        (_words("ai-outside-", 500), "1"),
        (_words("human-short-", 190), "0"),
        (_words("human-mid-", 250), "0"),
        (_words("human-high-", 310), "0"),
        (_words("human-higher-", 400), "0"),
        (_words("human-outside-", 100), "0"),
    )


def test_rebuild_is_order_independent_and_skips_rejected_sources(tmp_path: Path) -> None:
    sentence_rows = _sentence_fixture_rows()
    document_rows = _document_fixture_rows()
    first_sources = tmp_path / "first-sources"
    second_sources = tmp_path / "second-sources"
    first_output = tmp_path / "first-output"
    second_output = tmp_path / "second-output"
    _write_sources(first_sources, sentence_rows, document_rows)
    _write_sources(second_sources, tuple(reversed(sentence_rows)), tuple(reversed(document_rows)))
    first_output.mkdir()
    second_output.mkdir()
    first = build_slop_corpora.build_corpora(first_sources, first_output)
    second = build_slop_corpora.build_corpora(second_sources, second_output)
    assert first.keys() == second.keys() == EXPECTED_COUNTS.keys()
    for output_name in first:
        assert (first_output / output_name).read_bytes() == (second_output / output_name).read_bytes()
    document_rows_built = first[build_slop_corpora.DOCUMENT_OUTPUT_NAME]
    lengths = {len(row["text"].split()) for row in document_rows_built}
    assert lengths == {build_slop_corpora.DOCUMENT_TRUNCATE_WORDS}
    assert Counter(row["label"] for row in document_rows_built) == {"ai": 2, "human": 2}


def _leaking_rows(marker: str) -> list[dict]:
    return [
        {"label": "ai", "source": "s", "bias": "b", "text": marker + "generated text here"},
        {"label": "ai", "source": "s", "bias": "b", "text": marker + "more generated text"},
        {"label": "human", "source": "s", "bias": "b", "text": "written text here"},
        {"label": "human", "source": "s", "bias": "b", "text": "more written text"},
    ]


def test_leak_guard_refuses_a_corpus_separated_by_a_leading_quote() -> None:
    # WHY: Every measurement taken on this corpus is only as trustworthy as this guard refusing.
    try:
        build_slop_corpora._reject_leaks("test", _leaking_rows('"'))
    except ValueError as error:
        assert "leading quote" in str(error)
        return
    raise AssertionError("a corpus where every AI row starts with a quote must be refused")


def test_leak_guard_accepts_a_corpus_with_no_leading_quote_split() -> None:
    build_slop_corpora._reject_leaks("test", _leaking_rows(""))
