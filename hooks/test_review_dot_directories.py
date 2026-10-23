"""Real files here, because the model review decides on the path the agent edited, relative to the project it worked in."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import judge_review
import record
import stop
from lib import (
    claude_luna, claude_sonnet, embedding_session, journal, omp_review, parataxis_review, pattern_vote, reporting,
    session_state, temp_scope,
)
from lib.judge_contracts import RUBRIC_VERSION, JudgeRequest, JudgeResult, ReviewKind
from testing import init_repo

PROSE = "A paragraph with enough text to inspect for the review.\n"
COMMENT = "# Counts the retries because the report header needs a total.\nvalue = 1\n"
CHAIN = "The hook reads the file. It checks every rule. It writes a report.\n"
DASH = "This sentence uses an em dash " + chr(0x2014) + " which the punctuation family blocks.\n"
OUTSIDE = "../home/.claude/projects/x/memory/note.md"
EMPTY_VERDICT = json.dumps({"type": "result", "is_error": False, "structured_output": {"items": [], "notes": []}})
DOT_FILES = [".build/qa/cleanup/diffs.txt", ".claude/notes.md"]
PROJECT_FILES = [("project", "docs/guide.md"), ("project", ".github/CONTRIBUTING.md"), (".work/project", "docs/guide.md")]


@pytest.fixture(autouse=True)
def _no_temp_exemption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emptied, because pytest keeps every file under the OS temp root, where the scratch exemption would hide the outside path."""
    monkeypatch.setattr(temp_scope, "temp_roots", lambda: ())


@pytest.fixture(name="embedding_enabled")
def _embedding_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(embedding_session.ENABLE_ENV, "1")


def _project(path: Path) -> Path:
    path.mkdir(parents=True)
    init_repo(path)
    (path / ".agent-discipline.json").write_text(json.dumps({"data_boundary": {"enabled": True}}), encoding="utf-8")
    return path


def _written(path: Path, text: str = PROSE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _record(tmp_path: Path, project: Path, target: Path) -> dict:
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    return record.run({
        "session_id": "s1", "cwd": str(project), "tool_name": "Write", "tool_use_id": "t1",
        "tool_input": {"file_path": str(target)},
    }, config)


def _queued_documents(tmp_path: Path) -> list[dict]:
    return [row for row in journal.read("s1", state_root=tmp_path / "state") if row.get("role") == "document"]


def _queue_document(tmp_path: Path, target: Path) -> None:
    """Written as a literal row, because a queue filled before the fix must not reach the model either."""
    path = str(target.resolve())
    row = {
        "role": "document", "path": path, "path_identity": path, "content_hash": "queued",
        "source_context": PROSE, "source_truncated": False, "turn_id": "turn-1", "tool_use_id": "t1",
    }
    session_state.write_state("s1", {journal.STATE_KEY: [row], "turn_id": "turn-1"}, tmp_path / "state")


def _sonnet_prompts(tmp_path: Path, project: Path) -> list[str]:
    prompts: list[str] = []

    def judge(prompt: str) -> str:
        prompts.append(prompt)
        return EMPTY_VERDICT

    payload = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": False, "cwd": str(project)}
    claude_sonnet.run(payload, state_root=tmp_path / "state", judge=judge)
    return prompts


def _write_payload(project: Path, target: Path) -> dict:
    return {"session_id": "s1", "turn_id": "turn-1", "cwd": str(project), "tool_name": "Write", "tool_input": {"file_path": str(target)}}


def _queue_pattern(tmp_path: Path, target: Path) -> None:
    """Hashed like the file on disk, because OMP sends only the voted rows of the text it reviews."""
    path = str(target.resolve())
    row = {
        "role": "pattern", "rule": "ai_closer", "path": path, "path_identity": path, "line": 1, "text": PROSE.strip(),
        "content_hash": hashlib.sha256(PROSE.encode("utf-8")).hexdigest(), "turn_id": "turn-1",
    }
    session_state.write_state("s1", {journal.STATE_KEY: [row], "turn_id": "turn-1"}, tmp_path / "state")


def _omp_request_kinds(tmp_path: Path, project: Path, target: Path) -> list[str]:
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    prepared = omp_review.run({"operation": "prepare", "payload": _write_payload(project, target)}, config)
    return sorted(request["kind"] for request in prepared["requests"])


def _embedding_votes(project: Path, target: Path) -> list[str]:
    voted: list[str] = []
    voter = pattern_vote.Voter(
        open_turn=lambda *_args: "ready", renew_turn=lambda *_args: True,
        candidates=lambda path, _text, _config: voted.append(path) or {},
    )
    judge_review.run(_write_payload(project, target), voter=voter)
    return voted


@pytest.mark.parametrize("relative", [".build/qa/cleanup/diffs.txt", ".claude/notes.md", OUTSIDE])
def test_an_edit_under_a_dot_directory_queues_no_document_review(tmp_path: Path, relative: str) -> None:
    project = _project(tmp_path / "project")
    target = _written(project / relative)

    _record(tmp_path, project, target)

    assert _queued_documents(tmp_path) == []


@pytest.mark.parametrize(("project_dir", "relative"), PROJECT_FILES)
def test_an_edit_to_a_project_file_queues_one_document_review(tmp_path: Path, project_dir: str, relative: str) -> None:
    project = _project(tmp_path / project_dir)
    target = _written(project / relative)

    _record(tmp_path, project, target)

    assert len(_queued_documents(tmp_path)) == 1


def test_a_violating_file_under_a_dot_directory_still_gets_its_deterministic_findings(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    target = _written(project / ".build/qa/cleanup/diffs.txt", DASH)

    response = _record(tmp_path, project, target)

    rules = {row.get("rule") for row in reporting.read_jsonl(reporting.LEDGER_FILENAME, tmp_path / "ledger")}
    assert response.get("decision") == "block"
    assert "banned_dash" in rules


@pytest.mark.parametrize("relative", DOT_FILES)
def test_a_queued_document_under_a_dot_directory_is_not_sent_to_sonnet(tmp_path: Path, relative: str) -> None:
    project = _project(tmp_path / "project")
    _queue_document(tmp_path, _written(project / relative))

    assert _sonnet_prompts(tmp_path, project) == []


@pytest.mark.parametrize(("project_dir", "relative"), PROJECT_FILES)
def test_a_queued_project_document_is_sent_to_sonnet(tmp_path: Path, project_dir: str, relative: str) -> None:
    project = _project(tmp_path / project_dir)
    _queue_document(tmp_path, _written(project / relative))

    assert len(_sonnet_prompts(tmp_path, project)) == 1


def _codex_review(tmp_path: Path, project: Path) -> tuple[list[ReviewKind], dict]:
    calls: list[ReviewKind] = []

    def judge(request: JudgeRequest) -> JudgeResult:
        calls.append(request.review_kind)
        return JudgeResult({"notes": []}, "openai-codex", "gpt-5.6-luna", "high", RUBRIC_VERSION, {"total_tokens": 1})

    response = stop.run(
        {"session_id": "s1", "turn_id": "turn-1", "stop_hook_active": False, "cwd": str(project)},
        {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")},
        provider=SimpleNamespace(judge=judge),
    )
    return calls, response


def test_a_queued_document_under_a_dot_directory_is_not_sent_to_codex_luna(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    _queue_document(tmp_path, _written(project / ".claude/notes.md"))

    calls, response = _codex_review(tmp_path, project)

    assert calls == []
    assert "decision" not in response


def test_an_overflow_marker_for_a_hidden_path_leaves_the_codex_review_of_a_project_document_running(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    _queue_document(tmp_path, _written(project / "guide.md"))
    hidden = str(_written(project / ".build/notes.md").resolve())
    marker = {hidden: {"path_identity": hidden, "content_hash": "old", "turn_id": "turn-1"}}
    session_state.update_state("s1", lambda state: {**state, journal.OVERFLOW_KEY: marker}, tmp_path / "state")

    calls, response = _codex_review(tmp_path, project)

    assert calls == [ReviewKind.DOCUMENT]
    assert "decision" not in response


@pytest.mark.parametrize("relative", DOT_FILES)
def test_an_omp_review_of_a_dot_directory_file_prepares_no_model_request(tmp_path: Path, relative: str) -> None:
    project = _project(tmp_path / "project")
    target = _written(project / relative)
    _queue_pattern(tmp_path, target)

    assert _omp_request_kinds(tmp_path, project, target) == []


@pytest.mark.parametrize(("project_dir", "relative"), PROJECT_FILES)
def test_an_omp_review_of_a_project_file_prepares_its_document_and_queued_pattern(tmp_path: Path, project_dir: str, relative: str) -> None:
    project = _project(tmp_path / project_dir)
    target = _written(project / relative)
    _queue_pattern(tmp_path, target)

    assert _omp_request_kinds(tmp_path, project, target) == ["document", "pattern"]


@pytest.mark.usefixtures("embedding_enabled")
@pytest.mark.parametrize("relative", DOT_FILES)
def test_a_write_under_a_dot_directory_runs_no_embedding_vote(tmp_path: Path, relative: str) -> None:
    project = _project(tmp_path / "project")

    assert _embedding_votes(project, _written(project / relative)) == []


@pytest.mark.usefixtures("embedding_enabled")
@pytest.mark.parametrize(("project_dir", "relative"), PROJECT_FILES)
def test_a_project_write_runs_one_embedding_vote(tmp_path: Path, project_dir: str, relative: str) -> None:
    project = _project(tmp_path / project_dir)

    assert len(_embedding_votes(project, _written(project / relative))) == 1


def _live_comment_candidates(project: Path, target: Path) -> int:
    built = claude_luna.post_request({"hook_event_name": "PostToolUse", **_write_payload(project, target)})
    return 0 if built is None else len(built[1])


def _queued_runs(tmp_path: Path, target: Path) -> list[str]:
    parataxis_review.record(parataxis_review.EditTurn("s1", "turn-1", {}, tmp_path / "state"), target)
    return [row["rule"] for row in journal.read("s1", state_root=tmp_path / "state") if row["role"] == "pattern"]


def _queue_votes(tmp_path: Path, targets: list[Path]) -> None:
    """Forty rows per file, because that many votes from four files overfill the journal."""
    digest = hashlib.sha256(CHAIN.encode("utf-8")).hexdigest()
    rows = [{"rule": "ai_closer", "line": number + 1, "text": f"Row {number}"} for number in range(40)]
    for target in targets:
        journal.record_patterns("s1", "turn-1", _written(target, CHAIN), rows, content_hash=digest, state_root=tmp_path / "state")


def _full_stop_budget_of_patterns(project: Path, directory: str) -> list[dict]:
    """Enough full-size rows to fill the Stop budget, so a filter applied after the budget would starve the document."""
    count = journal.MAX_STOP_TOTAL_CHARS // journal.MAX_PATTERN_CHARS + 1
    return [{
        "role": "pattern", "rule": "ai_closer", "path": str(project / directory / "notes.md"), "content_hash": "old",
        "line": line, "text": "x" * journal.MAX_PATTERN_CHARS, "turn_id": "turn-1",
    } for line in range(1, count + 1)]


def _stop_roles(tmp_path: Path, project: Path, patterns: list[dict]) -> list[str]:
    document = {
        "role": "document", "path": str(_written(project / "notes.md")), "content_hash": "new", "turn_id": "turn-1",
        "before_context": "", "source_context": "The document needs a review.\n",
    }
    session_state.write_state("s1", {journal.STATE_KEY: [*patterns, document], "turn_id": "turn-1"}, tmp_path / "state")
    stop_payload = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": False, "cwd": str(project)}
    return [row["role"] for row in claude_luna.stop_rows(stop_payload, tmp_path / "state")]


def test_a_comment_under_a_dot_directory_gets_no_live_review(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    assert _live_comment_candidates(project, _written(project / ".build/tool.py", COMMENT)) == 0


def test_a_comment_in_a_project_file_gets_a_live_review(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    assert _live_comment_candidates(project, _written(project / "docs/tool.py", COMMENT)) == 1


def test_a_parataxis_run_under_a_dot_directory_queues_no_row(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    assert _queued_runs(tmp_path, _written(project / ".build/notes.md", CHAIN)) == []


def test_a_parataxis_run_in_a_project_file_queues_its_row(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    assert _queued_runs(tmp_path, _written(project / "docs/notes.md", CHAIN)) == ["choppy_sentences"]


def test_votes_for_hidden_files_do_not_push_a_project_document_out_of_the_journal(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    _record(tmp_path, project, _written(project / "guide.md"))

    _queue_votes(tmp_path, [project / ".build" / f"rows-{index}.md" for index in range(4)])

    assert [row["role"] for row in journal.read("s1", state_root=tmp_path / "state")].count("document") == 1


def test_votes_for_a_project_file_still_queue(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    _queue_votes(tmp_path, [project / "docs" / "rows.md"])

    assert len(journal.read("s1", state_root=tmp_path / "state")) == 40


def test_hidden_pattern_rows_leave_room_for_a_project_document_at_stop(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    assert _stop_roles(tmp_path, project, _full_stop_budget_of_patterns(project, ".build")) == ["document"]


def test_project_pattern_rows_still_reach_the_stop_review(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")

    assert "pattern" in _stop_roles(tmp_path, project, _full_stop_budget_of_patterns(project, "docs"))
