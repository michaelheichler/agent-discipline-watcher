"""Because partial journals cannot establish clean reviews, every host must expose omissions."""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

import pytest

from lib import claude_luna, claude_native, codex_luna, journal, omp_review, session_state
from lib.judge_contracts import JudgeResult, ReviewKind


@dataclass(frozen=True, slots=True)
class UnusedProvider:
    calls: list = field(default_factory=list)

    def judge(self, request: object) -> None:
        self.calls.append(request)
        raise AssertionError("Overflow must stop before provider work")


@pytest.fixture
def overflow_project(tmp_path: Path) -> dict:
    path = tmp_path / "note.md"
    path.write_text("The parser reads every record before the report runs.\n", encoding="utf-8")
    config = {"data_boundary": {"enabled": True}, "state_root": str(tmp_path / "state"),
              "ledger_root": str(tmp_path / "ledger")}
    (tmp_path / ".agent-discipline.json").write_text(json.dumps(config), encoding="utf-8")
    settings = tmp_path / "settings.json"
    preset = tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    return {"path": path, "config": config, "settings_path": settings, "preset_path": preset}


def put_marker(project: dict, kind: str) -> None:
    path = str(project["path"])
    marker = {"path_identity": path, "turn_id": "turn", "candidate_count": 4500,
              "omitted_count": 404}
    if kind == "sentinel":
        marker["path_identity"] = journal.OVERFLOW_SENTINEL
    elif kind == "malformed":
        marker.pop("path_identity")
    session_state.update_state(
        "overflow", lambda state: {**state, journal.OVERFLOW_KEY: {path: marker}},
        project["config"]["state_root"],
    )


def stop_payload(project: dict) -> dict:
    return {"hook_event_name": "Stop", "session_id": "overflow", "turn_id": "turn",
            "cwd": str(project["path"].parent),
            "tool_input": {"file_path": str(project["path"])}}


FAILURES = [
    pytest.param("overflow", r"4500.*404", id="omitted-counts"),
    pytest.param("sentinel", r"new session", id="new-session-required"),
    pytest.param("malformed", r"malformed|invalid", id="invalid-marker"),
]


@pytest.mark.parametrize("kind, diagnostic", FAILURES)
def test_claude_stop_exposes_incomplete_journals_before_provider_work(
    overflow_project: dict, kind: str, diagnostic: str,
) -> None:
    put_marker(overflow_project, kind)
    provider = UnusedProvider()

    result = claude_luna.run(
        stop_payload(overflow_project), provider=provider,
        state_root=overflow_project["config"]["state_root"],
        settings_path=overflow_project["settings_path"], preset_path=overflow_project["preset_path"],
    )

    assert result["decision"] == "block"
    assert re.search(diagnostic, result["reason"])
    assert provider.calls == []


@pytest.mark.parametrize("kind, diagnostic", FAILURES)
def test_codex_stop_exposes_incomplete_journals_before_provider_work(
    overflow_project: dict, kind: str, diagnostic: str,
) -> None:
    put_marker(overflow_project, kind)
    provider = UnusedProvider()

    result = codex_luna.review(
        stop_payload(overflow_project), turn_id="turn", provider=provider,
        state_root=overflow_project["config"]["state_root"],
    )

    assert result["decision"] == "block"
    assert re.search(diagnostic, result["reason"])
    assert provider.calls == []


@pytest.mark.parametrize("kind, diagnostic", FAILURES)
def test_omp_prepare_exposes_incomplete_journals_before_returning_model_work(
    overflow_project: dict, kind: str, diagnostic: str,
) -> None:
    put_marker(overflow_project, kind)

    with pytest.raises(ValueError, match=diagnostic):
        omp_review.run({"operation": "prepare", "payload": stop_payload(overflow_project)},
                       overflow_project["config"])


def test_codex_excludes_overflow_for_a_hidden_file_outside_review(overflow_project: dict) -> None:
    path = str(overflow_project["path"].parent / ".hidden" / "note.md")
    session_state.write_state("overflow", {journal.OVERFLOW_KEY: {path: {
        "path_identity": path, "turn_id": "turn", "candidate_count": 4500, "omitted_count": 404,
    }}}, overflow_project["config"]["state_root"])
    provider = UnusedProvider()

    result = codex_luna.review(stop_payload(overflow_project), turn_id="turn", provider=provider,
                               state_root=overflow_project["config"]["state_root"])

    assert result == {}
    assert provider.calls == []


@pytest.mark.parametrize("host, enabled", [("claude", None), ("codex", None), ("omp", True)])
def test_missing_overflow_metadata_preserves_normal_host_review(
    overflow_project: dict, host: str, enabled: bool | None,
) -> None:
    provider = UnusedProvider()
    payload = stop_payload(overflow_project)
    readers = {
        "claude": lambda: claude_luna.run(
            payload, provider=provider, state_root=overflow_project["config"]["state_root"],
            settings_path=overflow_project["settings_path"],
            preset_path=overflow_project["preset_path"],
        ),
        "codex": lambda: codex_luna.review(
            payload, turn_id="turn", provider=provider,
            state_root=overflow_project["config"]["state_root"],
        ),
        "omp": lambda: omp_review.run({"operation": "prepare", "payload": payload},
                                      overflow_project["config"]),
    }

    result = readers[host]()

    assert result.get("decision") is None
    assert result.get("enabled") is enabled
    assert provider.calls == []


@dataclass(frozen=True, slots=True)
class UpholdingProvider:
    def judge(self, request) -> JudgeResult:
        return JudgeResult(
            payload={
                ReviewKind.DOCUMENT: {"notes": []},
                ReviewKind.PATTERN: {"items": [{"index": 0, "verdict": "violating",
                                               "reason": "A persisted pattern verdict."}]},
            }[request.review_kind],
            provider="fixture", model="fixture", effort="high",
            rubric_version=request.rubric_version, usage={},
        )


@pytest.fixture
def held_overflow(overflow_project: dict) -> tuple[dict, str]:
    source = overflow_project["path"]
    project = overflow_project
    root = project["config"]["state_root"]
    closer = "Feel free to ask me anything else.\n"
    source.write_text(closer, encoding="utf-8")
    config = {**project["config"], "rule_gates": {"ai_closer": "enforce"}}
    (source.parent / ".agent-discipline.json").write_text(json.dumps(config), encoding="utf-8")
    journal.record_patterns(
        "overflow", "turn", source, [{"rule": "ai_closer", "line": 1, "text": closer.strip()}],
        content_hash=hashlib.sha256(closer.encode()).hexdigest(), state_root=root,
        project=source.parent,
    )
    result = claude_luna.run(
        stop_payload(project), provider=UpholdingProvider(), state_root=root,
        settings_path=project["settings_path"], preset_path=project["preset_path"],
    )
    assert result["decision"] == "block"
    entries = journal.upheld("overflow", state_root=root)
    assert entries, session_state.read_state("overflow", root)
    held, = entries
    put_marker(project, "overflow")
    return project, held


def test_overflow_keeps_a_previously_upheld_verdict_visible(held_overflow: tuple) -> None:
    project, held = held_overflow
    provider = UnusedProvider()

    result = claude_luna.run(
        stop_payload(project), provider=provider, state_root=project["config"]["state_root"],
        settings_path=project["settings_path"], preset_path=project["preset_path"],
    )

    assert result["decision"] == "block"
    assert held in result["reason"]
    assert re.search(r"4500.*404", result["reason"])
    assert provider.calls == []


CORRUPT_STATES = [
    pytest.param({journal.STATE_KEY: "not-a-row-list"}, id="non-list-journal"),
    pytest.param({journal.STATE_KEY: [None]}, id="null-row"),
    pytest.param({journal.STATE_KEY: ["not-an-object"]}, id="non-object-row"),
    pytest.param({journal.OVERFLOW_KEY: None}, id="null-overflow-metadata"),
]


@pytest.mark.parametrize("state", CORRUPT_STATES)
def test_claude_does_not_treat_corrupt_journal_rows_as_a_clean_review(
    overflow_project: dict, state: dict,
) -> None:
    session_state.write_state("overflow", state, overflow_project["config"]["state_root"])
    provider = UnusedProvider()

    result = claude_luna.run(stop_payload(overflow_project), provider=provider,
                             state_root=overflow_project["config"]["state_root"],
                             settings_path=overflow_project["settings_path"],
                             preset_path=overflow_project["preset_path"])

    assert result["decision"] == "block"
    assert result["reason"].strip()
    assert provider.calls == []


@pytest.mark.parametrize("state", CORRUPT_STATES)
def test_codex_does_not_treat_corrupt_journal_rows_as_a_clean_review(
    overflow_project: dict, state: dict,
) -> None:
    session_state.write_state("overflow", state, overflow_project["config"]["state_root"])
    provider = UnusedProvider()

    result = codex_luna.review(stop_payload(overflow_project), turn_id="turn", provider=provider,
                               state_root=overflow_project["config"]["state_root"])

    assert result["decision"] == "block"
    assert result["reason"].strip()
    assert provider.calls == []


@pytest.mark.parametrize("state", CORRUPT_STATES)
def test_omp_does_not_treat_corrupt_journal_rows_as_a_clean_review(
    overflow_project: dict, state: dict,
) -> None:
    session_state.write_state("overflow", state, overflow_project["config"]["state_root"])

    with pytest.raises(ValueError):
        omp_review.run({"operation": "prepare", "payload": stop_payload(overflow_project)},
                       overflow_project["config"])
