"""Behavior of the post-write language route, because Codex must never wait on Luna and Claude must not pay twice."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.judge_contracts import JudgeRequest
from lib.language_route import ProseWrite, after_write, drain, start_drain
from lib.language_verdict import StateRoot, apply_cached
from lib.prose_language import paragraph_languages

ENGLISH = (
    "The report shows that the measurement on the German corpus is not finished yet, "
    "so we set the threshold only after it is in."
)
GREETING = "Vielen Dank."
DOCUMENT = f"{ENGLISH}\n\n{GREETING}\n"


class FakeLuna:
    """Faked, because a test must never reach the network."""

    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []

    def __call__(self, request: JudgeRequest) -> SimpleNamespace:
        self.requests.append(request)
        return SimpleNamespace(payload={"items": [{"index": 0, "language": "de"}]})

    def calls(self) -> int:
        return len(self.requests)


def refuse(_request: JudgeRequest) -> SimpleNamespace:
    raise AssertionError("a hook waited on Luna")


@pytest.fixture(name="project")
def _project(tmp_path: Path) -> SimpleNamespace:
    notes = tmp_path / "notes.md"
    notes.write_text(DOCUMENT, encoding="utf-8")
    config = {"data_boundary": {"enabled": True}, "state_root": str(tmp_path / "state")}
    return SimpleNamespace(notes=notes, config=config, root=config["state_root"])


def _write(project: SimpleNamespace, *, codex: bool) -> ProseWrite:
    return ProseWrite("s1", (project.notes,), project.config, codex)


def _greeting_language(root: StateRoot) -> str:
    return apply_cached(paragraph_languages(DOCUMENT), root)[1].language


def test_a_second_write_of_the_same_weak_paragraph_makes_no_luna_call(project: SimpleNamespace) -> None:
    luna = FakeLuna()

    after_write(_write(project, codex=False), luna)
    after_write(_write(project, codex=False), luna)

    assert luna.calls() == 1


def test_claude_corrects_the_paragraph_right_after_the_write(project: SimpleNamespace) -> None:
    after_write(_write(project, codex=False), FakeLuna())

    assert _greeting_language(project.root) == "de"


def test_a_codex_write_never_calls_luna(project: SimpleNamespace) -> None:
    after_write(_write(project, codex=True), refuse)

    assert _greeting_language(project.root) == "en"


def test_the_next_codex_prompt_starts_the_drain_without_waiting(project: SimpleNamespace) -> None:
    after_write(_write(project, codex=True), refuse)
    spawned: list[tuple[str, StateRoot]] = []

    start_drain("s1", project.config, lambda session, root: spawned.append((session, root)))

    assert spawned == [("s1", project.root)]


def test_the_background_drain_corrects_the_codex_guess(project: SimpleNamespace) -> None:
    after_write(_write(project, codex=True), refuse)

    drain("s1", project.root, FakeLuna())

    assert _greeting_language(project.root) == "de"


def test_an_empty_queue_starts_no_background_process(project: SimpleNamespace) -> None:
    spawned: list[tuple[str, StateRoot]] = []

    start_drain("s1", project.config, lambda session, root: spawned.append((session, root)))

    assert spawned == []


def test_a_failed_spawn_leaves_the_prompt_hook_running(project: SimpleNamespace) -> None:
    after_write(_write(project, codex=True), refuse)

    def broken(_session: str, _root: StateRoot) -> None:
        raise OSError("fork failed")

    assert start_drain("s1", project.config, broken) is False


def test_without_a_data_boundary_no_paragraph_leaves_the_machine(project: SimpleNamespace) -> None:
    luna = FakeLuna()
    closed = ProseWrite("s1", (project.notes,), {"state_root": project.root}, False)

    after_write(closed, luna)

    assert luna.calls() == 0
