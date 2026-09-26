from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

import judge_review
from lib import embedding_session, host, journal, pattern_judge, pattern_vote, session_state
from lib.hookio import PARSE_FAILURE
from lib.pattern_judge import PatternCandidate

CLOSER = "Feel free to ask me anything else."
WARM_URL = "http://127.0.0.1:1/v1/embeddings"
ROUTE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch"


@dataclass
class Route:
    root: Path
    workspace: Path
    calls: list[str]
    monkeypatch: pytest.MonkeyPatch

    def write(self, name: str) -> Path:
        target = self.workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{CLOSER}\n", encoding="utf-8")
        return target

    def vote_closers(self) -> None:
        self.monkeypatch.setattr(
            pattern_vote, "candidates",
            lambda path, text, _config: {"ai_closer": (PatternCandidate(path, 1, text.strip()),)},
        )

    def forbid_vote(self) -> None:
        self.monkeypatch.setattr(pattern_vote, "candidates", lambda *_args: pytest.fail("voted"))

    def feed(self, payload: dict) -> None:
        self.monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


@pytest.fixture(name="route")
def _route(tmp_path, monkeypatch) -> Route:
    root = tmp_path / "state"
    calls: list[str] = []
    monkeypatch.setattr(session_state, "_default_root", lambda: root)
    monkeypatch.setattr(pattern_judge, "confirm_all", lambda *_args: pytest.fail("called a model"))
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")
    monkeypatch.setattr(
        embedding_session, "open_turn", lambda session, _root: calls.append(f"open:{session}") or WARM_URL,
    )
    monkeypatch.setattr(embedding_session, "renew_turn", lambda session, _root: calls.append(f"renew:{session}"))
    monkeypatch.setattr(pattern_vote.time, "sleep", lambda _seconds: None)
    return Route(root, tmp_path / "work", calls, monkeypatch)


def _payload(path: Path, session_id: str = "vote") -> dict:
    return {
        "cwd": str(path.parent), "tool_name": "Write", "session_id": session_id,
        "turn_id": "turn-1", "tool_input": {"file_path": str(path)},
    }


def _patterns(session_id: str) -> list[dict]:
    rows = session_state.read_state(session_id, None).get(journal.STATE_KEY, [])
    return [row for row in rows if row.get("role") == "pattern"]


def test_importing_the_route_registers_the_embedding_consumer() -> None:
    probe = "import judge_review\nfrom lib import embedding_session\nprint(embedding_session.CONSUMER_REGISTERED)"
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=Path(judge_review.__file__).parent,
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == "True"


def test_every_voted_sentence_lands_in_the_journal(route: Route) -> None:
    route.vote_closers()

    judge_review.run(_payload(route.write("notes.md")))

    [row] = _patterns("vote")
    assert (row["rule"], row["line"], row["text"], row["turn_id"]) == ("ai_closer", 1, CLOSER, "turn-1")


def test_a_prose_write_keeps_the_embedding_lease(route: Route) -> None:
    route.vote_closers()

    judge_review.run(_payload(route.write("notes.md")))

    assert route.calls == ["open:vote", "renew:vote"]


def test_a_cold_model_is_awaited_before_the_vote(route: Route) -> None:
    answers = iter([None, None, WARM_URL])
    route.monkeypatch.setattr(embedding_session, "open_turn", lambda *_args: None)
    route.monkeypatch.setattr(pattern_vote, "probe", lambda: next(answers))
    route.vote_closers()

    judge_review.run(_payload(route.write("notes.md")))

    assert _patterns("vote")


def test_a_model_that_never_answers_skips_the_vote(route: Route) -> None:
    route.monkeypatch.setattr(embedding_session, "open_turn", lambda *_args: None)
    route.monkeypatch.setattr(pattern_vote, "probe", lambda: None)
    route.monkeypatch.setattr(judge_review, "READY_WAIT_SECONDS", 0.0)
    route.forbid_vote()

    judge_review.run(_payload(route.write("notes.md")))

    assert not _patterns("vote")


def test_a_switched_off_layer_never_opens_a_turn(route: Route) -> None:
    route.monkeypatch.delenv(embedding_session.ENABLE_ENV)
    route.forbid_vote()

    judge_review.run(_payload(route.write("notes.md")))

    assert route.calls == []


def test_a_code_file_is_never_voted(route: Route) -> None:
    route.forbid_vote()

    judge_review.run(_payload(route.write("tool.py")))

    assert route.calls == []
    assert not route.root.exists()


def test_a_session_scratch_file_is_never_voted(route: Route) -> None:
    route.monkeypatch.setattr(judge_review, "TEMP_ROOTS", (route.workspace,))
    route.forbid_vote()

    judge_review.run(_payload(route.write("scratchpad/notes.md")))

    assert route.calls == []
    assert not route.root.exists()


def test_a_write_without_a_session_is_left_alone(route: Route) -> None:
    route.forbid_vote()

    judge_review.run(_payload(route.write("notes.md"), session_id=""))

    assert route.calls == []
    assert not route.root.exists()


def test_a_broken_payload_is_left_alone(route: Route) -> None:
    judge_review.run(PARSE_FAILURE)

    assert route.calls == []
    assert not route.root.exists()


def test_the_route_exits_cleanly_and_prints_nothing(route: Route, capsys) -> None:
    route.vote_closers()
    route.feed(_payload(route.write("notes.md")))

    assert judge_review.main() == 0

    assert capsys.readouterr().out == ""
    assert _patterns("vote")


def _route_entries(manifest: str) -> list[tuple[str, dict]]:
    config = json.loads((Path(judge_review.__file__).parent / manifest).read_text(encoding="utf-8"))
    return [
        (group.get("matcher", ""), hook)
        for group in config["hooks"]["PostToolUse"]
        for hook in group["hooks"]
        if str(hook.get("command", "")).endswith(" JudgeReview")
    ]


def test_claude_runs_the_vote_detached_after_each_write() -> None:
    [(matcher, hook)] = _route_entries("hooks.json")

    assert matcher == ROUTE_MATCHER
    assert (hook["async"], hook["timeout"]) == (True, 180)
    assert "asyncRewake" not in hook


def test_codex_runs_the_vote_inline_because_it_ignores_async() -> None:
    [(matcher, hook)] = _route_entries("codex-hooks.json")

    assert matcher == ROUTE_MATCHER
    assert hook["timeout"] == judge_review.CODEX_HOOK_TIMEOUT_SECONDS == 10
    assert "async" not in hook


def test_the_codex_budget_ends_the_route_before_its_hook_timeout(route: Route) -> None:
    release = threading.Event()
    route.monkeypatch.setenv(host.CODEX_ENV, "1")
    route.monkeypatch.setattr(judge_review, "CODEX_BUDGET_SECONDS", 0.05)
    route.monkeypatch.setattr(judge_review, "run", lambda _payload: release.wait(5))
    route.feed({})
    started = time.monotonic()

    assert judge_review.main() == 0

    assert time.monotonic() - started < 1
    assert judge_review.CODEX_BUDGET_SECONDS < judge_review.CODEX_HOOK_TIMEOUT_SECONDS
    release.set()


def test_a_failed_vote_still_exits_cleanly(route: Route, capsys) -> None:
    def broken(*_args) -> dict:
        raise ValueError("embedding server returned 1 vectors for 2 inputs")

    route.monkeypatch.setattr(pattern_vote, "candidates", broken)
    route.feed(_payload(route.write("notes.md")))

    assert judge_review.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "embedding server returned" in captured.err
    assert not _patterns("vote")
