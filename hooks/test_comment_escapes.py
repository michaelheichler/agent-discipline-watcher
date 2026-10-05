from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from lib.comment_rules import SUBJECT_OPENER_RE
from lib.scanner import scan_all

ARTICLE_RE = re.compile(r"^(?:The|A|An|This|That|Each|Every|One|Its)\s+")
SWIFT_MARK = "// " + "MARK" + ": Setup\nlet a = 1\n"


def _rules(source: str, path: str = "sample.py") -> set[str]:
    return {row["rule"] for row in scan_all(path, source, {})}


def _comment_rules(comment: str) -> set[str]:
    return _rules("# " + comment + "\nx = 1\n")


@pytest.mark.parametrize("comment", [
    "Reader votes a sentence, so the vote stays stable.",
    "Loader reads the file, so the cache stays warm.",
    "Cache stores the last result because reuse is faster.",
    "Disk cache writes the entry to a file, so the entry is persisted.",
    "Network client retries the request, so failures are handled.",
    "Dispatcher routes each event to its subscriber list, so every subscriber hears it.",
    "Handler returns the response because callers need a result.",
])
def test_dropping_the_article_does_not_hide_narration(comment: str) -> None:
    assert "what_comment" in _comment_rules(comment)


@pytest.mark.parametrize("comment", [
    "Callers need stable identity, because a fresh read renumbers every row.",
    "Empty feeders end a batch with a non-zero status, so pages count as success.",
    "Files instead of pipes, because a full pipe buffer would block scanimage.",
    "Skip empty files to avoid a divide by zero in the ratio.",
    "Skip rows a third rater already decided, because an extension must not resend them.",
    "Give model rows one shape, because the reader acts on the same three parts.",
    "Only rules the hook would send, because a silent rule has no stage to measure.",
    "Keep this sorted because the binary search below depends on it.",
])
def test_a_noun_or_imperative_opener_that_states_a_decision_still_passes(comment: str) -> None:
    assert "what_comment" not in _comment_rules(comment)


def _corpus_comments(label: str) -> list[str]:
    corpus = Path(__file__).parent / "lib" / "corpus_what_comments.jsonl"
    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line]
    return [row["text"] for row in rows if row["kind"] == "comment" and row["label"] == label]


def test_every_narration_comment_in_the_corpus_is_blocked() -> None:
    escaped = [text for text in _corpus_comments("what") if not {"what_comment", "prose_semicolon"} & _comment_rules(text)]
    assert escaped == []


def _article_dropped_narrations() -> list[str]:
    articled = [text for text in _corpus_comments("what") if SUBJECT_OPENER_RE.match(text)]
    remainders = [ARTICLE_RE.sub("", text) for text in articled]
    return [text[0].upper() + text[1:] for text in remainders]


def test_most_article_dropped_corpus_narrations_are_blocked() -> None:
    dropped = _article_dropped_narrations()
    escaped = [text for text in dropped if "what_comment" not in _comment_rules(text)]
    assert len(dropped) >= 60
    assert len(escaped) <= 25, escaped


@pytest.mark.parametrize("comment", [
    "note: this loops over every page and returns the count",
    "noqa: E501 loops over every page",
    "pylint: loops over every page and returns the count",
    "Note: loops over every page and returns the count",
])
def test_a_generic_label_does_not_hide_narration_after_the_colon(comment: str) -> None:
    assert "what_comment" in _comment_rules(comment)


def test_an_inline_directive_does_not_hide_narration_after_it() -> None:
    assert "what_comment" in _rules("x = 1  # noqa: E501 loops over every page\n")


@pytest.mark.parametrize("comment", [
    "WHY: Callers need stable identity because a fresh read renumbers every row",
    "WHY: the vendor caps traffic at 100 requests a minute",
    "invariant: the queue is never empty",
    "Note: keep the cache because callers rely on stable identity",
    ("TO" + "DO") + ": loop over every page",
])
def test_structured_tags_and_labelled_reasons_still_pass(comment: str) -> None:
    assert "what_comment" not in _comment_rules(comment)


@pytest.mark.parametrize("source, path", [
    ("x = 1  # noqa: E501\n", "sample.py"),
    ("x = 1  # noqa\n", "sample.py"),
    ("x = 1  # type: ignore[arg-type]\n", "sample.py"),
    ("x = 1  # pylint: disable=too-many-lines,wrong-import-position\n", "sample.py"),
    ("x = 1  # noqa: E402  # pylint: disable=wrong-import-position\n", "sample.py"),
    ("x = 1  # pyright: ignore[reportGeneralTypeIssues]\n", "sample.py"),
    ("x = 1  # isort: skip\n", "sample.py"),
    ("x = 1  # mypy: ignore-errors\n", "sample.py"),
    (SWIFT_MARK, "Runner.swift"),
])
def test_real_tool_directives_still_pass(source: str, path: str) -> None:
    assert "what_comment" not in _rules(source, path)


def test_a_docstring_section_label_still_covers_the_entries_below_it() -> None:
    source = (
        'def fetch(items):\n'
        '    """Load stable rows because callers need them.\n\n'
        '    Args:\n'
        '        items: the rows\n'
        '    """\n'
        '    return items\n'
    )
    assert "what_docstring" not in _rules(source)


def test_a_labelled_docstring_line_that_narrates_is_a_what_docstring() -> None:
    assert "what_docstring" in _rules('def scan():\n    """Note: loops over every page."""\n')


@pytest.mark.parametrize("reason", [
    "this loops over the pages",
    "loops over every page and returns the count",
])
@pytest.mark.parametrize("directive", ["@ts-expect-error", "@ts-ignore"])
def test_a_ts_directive_reason_that_narrates_is_blocked(directive: str, reason: str) -> None:
    assert "what_comment" in _rules("// " + directive + " " + reason + "\nrun()\n", "sample.ts")


@pytest.mark.parametrize("comment", ["@ts-foo anything at all", "@ts-expect-errors this loops over pages"])
def test_an_unknown_ts_directive_name_is_a_plain_comment(comment: str) -> None:
    assert "what_comment" in _rules("// " + comment + "\nrun()\n", "sample.ts")


@pytest.mark.parametrize("comment", [
    "@ts-ignore",
    "@ts-expect-error",
    "@ts-nocheck",
    "@ts-check",
    "@ts-expect-error the vendor typings omit this field, because the SDK is untyped",
])
def test_real_ts_directives_and_reasoned_ones_still_pass(comment: str) -> None:
    assert _rules("// " + comment + "\nrun()\n", "sample.ts") == set()
