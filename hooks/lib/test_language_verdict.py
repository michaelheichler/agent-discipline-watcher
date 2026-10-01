"""Behavior of the verdict cache, because a lost verdict costs a Luna call and a wrong one swaps the rule set."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.judge_contracts import JudgeRequest, ReviewKind
from lib.language_verdict import apply_cached, cached_language, classify
from lib.luna_storage import LunaProviderFailure
from lib.luna_validation import validate_worker_result
from lib.prose_language import paragraph_languages

ENGLISH = (
    "The report shows that the measurement on the German corpus is not finished yet, "
    "so we set the threshold only after it is in."
)
GREETING = "Vielen Dank."


class FakeLuna:
    """Faked, because a test must never reach the network."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.requests: list[JudgeRequest] = []

    def __call__(self, request: JudgeRequest) -> SimpleNamespace:
        self.requests.append(request)
        items = [
            {"index": index, "language": self.answers[text]}
            for index, text in enumerate(request.candidates) if text in self.answers
        ]
        return SimpleNamespace(payload={"items": items})

    def sent(self) -> list[tuple[str, ...]]:
        return [request.candidates for request in self.requests]


@pytest.fixture(name="state_root")
def _state_root(tmp_path: Path) -> Path:
    return tmp_path / "state"


def _greeting_language(state_root: Path) -> tuple[str, bool]:
    rows = apply_cached(paragraph_languages(f"{ENGLISH}\n\n{GREETING}\n"), state_root)
    return rows[1].language, rows[1].weak


def test_a_luna_verdict_corrects_the_document_language_guess(state_root: Path) -> None:
    classify([GREETING], FakeLuna({GREETING: "de"}), state_root)

    assert _greeting_language(state_root) == ("de", False)


def test_a_paragraph_without_a_verdict_keeps_the_document_language(state_root: Path) -> None:
    assert _greeting_language(state_root) == ("en", True)


def test_reflowed_whitespace_finds_the_same_verdict(state_root: Path) -> None:
    classify(["Vielen   Dank.\n"], FakeLuna({"Vielen Dank.": "de"}), state_root)

    assert cached_language(GREETING, state_root) == "de"


def test_an_answer_outside_de_and_en_is_no_verdict(state_root: Path) -> None:
    verdicts = classify([GREETING], FakeLuna({GREETING: "fr"}), state_root)

    assert (verdicts, cached_language(GREETING, state_root)) == ({}, None)


def test_a_row_with_an_extra_field_is_no_verdict(state_root: Path) -> None:
    def chatty(_request: JudgeRequest) -> SimpleNamespace:
        return SimpleNamespace(payload={"items": [{"index": 0, "language": "de", "reason": "umlaut"}]})

    assert classify([GREETING], chatty, state_root) == {}


def test_two_answers_for_one_paragraph_are_no_verdict(state_root: Path) -> None:
    def torn(_request: JudgeRequest) -> SimpleNamespace:
        return SimpleNamespace(payload={"items": [{"index": 0, "language": "de"}, {"index": 0, "language": "en"}]})

    assert classify([GREETING], torn, state_root) == {}


def test_a_luna_outage_caches_nothing(state_root: Path) -> None:
    def down(_request: JudgeRequest) -> SimpleNamespace:
        raise LunaProviderFailure("Luna judge timed out", category="timeout")

    classify([GREETING], down, state_root)

    assert cached_language(GREETING, state_root) is None


def test_a_strong_paragraph_ignores_a_cached_verdict(state_root: Path) -> None:
    classify([ENGLISH], FakeLuna({ENGLISH: "de"}), state_root)

    rows = apply_cached(paragraph_languages(f"{ENGLISH}\n"), state_root)

    assert (rows[0].language, rows[0].weak) == ("en", False)


def _worker_row(language: str) -> dict[str, object]:
    return {
        "payload": {"items": [{"index": 0, "language": language}]},
        "provider": "openai-codex", "model": "gpt-5.6-luna", "effort": "high",
        "rubric_version": "adw-rubric-v1", "usage": {}, "cached": False,
    }


def test_the_luna_worker_contract_accepts_a_language_answer() -> None:
    request = JudgeRequest(ReviewKind.LANGUAGE, candidates=(GREETING,))

    result = validate_worker_result(request, _worker_row("de"), "openai-codex", "high")

    assert result.payload["items"] == [{"index": 0, "language": "de"}]


def test_the_luna_worker_contract_rejects_a_third_language() -> None:
    request = JudgeRequest(ReviewKind.LANGUAGE, candidates=(GREETING,))

    with pytest.raises(LunaProviderFailure):
        validate_worker_result(request, _worker_row("fr"), "openai-codex", "high")


def test_a_repeated_paragraph_is_sent_once(state_root: Path) -> None:
    luna = FakeLuna({GREETING: "de"})

    classify([GREETING, GREETING], luna, state_root)

    assert luna.sent() == [(GREETING,)]
