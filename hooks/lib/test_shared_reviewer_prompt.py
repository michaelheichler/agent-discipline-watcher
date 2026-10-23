"""Kept apart, because a reviewer that never hears a gate budget flags text the gate forced into shape."""
from __future__ import annotations

import io
import json
import os
import re
import stat
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import pytest
from pytest import MonkeyPatch

from lib import (
    claude_luna, claude_native, claude_sonnet, codex_luna, comment_rules, config, journal, judge_contracts,
    language_verdict, luna_worker, prose_language, session_state,
)
from lib.document_review import HUNK_NOTICE
from lib.judge_contracts import (
    COMMENT_RUBRIC, DOCUMENT_RUBRIC, GERMAN_PATTERN_RUBRIC, LANGUAGE_RUBRIC, PATTERN_RUBRIC,
    JudgeRequest, JudgeResult, ReviewKind, build_prompt,
)
from lib.luna_provider import (
    CONFIG_OVERRIDES, LUNA_MODEL, LunaJudge, SdkAccount, SdkItem, SdkLaunch, SdkModel, SdkRunResult,
    SdkThreadStart, SdkTurn,
)
from lib.luna_worker_protocol import request_payload

SESSION, TURN = "shared", "turn-1"
CHANGED = "The parser reads every record before the report runs."
CLOSER = "Feel free to ask me anything else."
GERMAN = "An dieser Stelle sei gesagt, dass der Bericht fertig ist."
CUSTOM_LIST_CAP = config.DEFAULTS["list_item_cap"] + 1
OPEN_BOUNDARY = {"data_boundary": {"enabled": True}, "rule_gates": {"ai_closer": "enforce", "de_stock_phrase": "enforce"}}
RUBRICS = (
    ("comment", COMMENT_RUBRIC), ("pattern", PATTERN_RUBRIC), ("german pattern", GERMAN_PATTERN_RUBRIC),
    ("document", DOCUMENT_RUBRIC), ("language", LANGUAGE_RUBRIC), ("hunk notice", HUNK_NOTICE),
)
CLI_REPLY = {"type": "result", "is_error": False, "structured_output": {"items": [], "notes": []}}
MIXED_PARAGRAPH = "Das Release folgt morgen, and the notes follow later."


@dataclass(frozen=True)
class Call:
    system: str
    user: str

    def occurrences(self, text: str) -> int:
        return f"{self.system}\n{self.user}".count(text)


Reviewer = Callable[[Path, MonkeyPatch, Path], list[Call]]
Operation = Callable[[], SdkRunResult]


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Redirected, because reviewers write reports and ledger rows under the home directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _config(cwd: Path, settings: dict[str, Any]) -> dict:
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / ".agent-discipline.json").write_text(json.dumps({**OPEN_BOUNDARY, **settings}), encoding="utf-8")
    return config.effective_hook_config({}, str(cwd))


def _states(text: str, number: int) -> bool:
    return re.search(rf"(?<!\d){number}(?!\d)", text) is not None


def _begin_turn(tmp_path: Path, turn: str = TURN) -> Path:
    state_root = tmp_path / "state"
    session_state.update_state(SESSION, lambda state: {**state, "turn_id": turn}, state_root)
    return state_root


def _document_turn(tmp_path: Path) -> Path:
    """Off the default cap, because a reviewer that ignores project config must then send a different block."""
    _config(tmp_path, {"list_item_cap": CUSTOM_LIST_CAP})
    notes = tmp_path / "notes.md"
    notes.write_text(f"{CHANGED}\n", encoding="utf-8")
    journal.record_edit(SESSION, TURN, "tool-1", notes, state_root=tmp_path / "state")
    return _begin_turn(tmp_path)


def _mixed_turn(tmp_path: Path) -> Path:
    """Every review kind in one turn, because a duplicate rubric can hide in any of them."""
    _config(tmp_path, {})
    state_root = tmp_path / "state"
    notes, code = tmp_path / "notes.md", tmp_path / "code.py"
    notes.write_text(f"{CHANGED}\n{CLOSER}\n{GERMAN}\n", encoding="utf-8")
    code.write_text("# Returns the result because the caller needs a value.\nVALUE = 1\n", encoding="utf-8")
    journal.record_edit(SESSION, TURN, "tool-1", notes, state_root=state_root)
    journal.record_edit(SESSION, TURN, "tool-2", code, state_root=state_root)
    digest = journal.current_source(notes)[0]
    rows = [{"rule": "ai_closer", "line": 2, "text": CLOSER}, {"rule": "de_stock_phrase", "line": 3, "text": GERMAN}]
    journal.record_patterns(SESSION, TURN, notes, rows, content_hash=digest, state_root=state_root)
    return _begin_turn(tmp_path)


def _two_line_edit(tmp_path: Path) -> Path:
    _config(tmp_path, {})
    state_root = tmp_path / "state"
    readme = tmp_path / "README.md"
    sentences = [f"Sentence {number} of the untouched README." for number in range(1, 481)]
    readme.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    journal.record_edit(SESSION, "turn-1", "tool-1", readme, state_root=state_root)
    journal.mark_reviewed(SESSION, journal.read_stop(SESSION, turn_id="turn-1", state_root=state_root), state_root=state_root)
    sentences[99:101] = ["The preset picks the reviewer.", "It also names the model."]
    readme.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    journal.record_edit(SESSION, "turn-2", "tool-2", readme, state_root=state_root)
    return _begin_turn(tmp_path, "turn-2")


def _stop_payload(tmp_path: Path) -> dict:
    return {"hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": False, "cwd": str(tmp_path)}


def _codex_payload(tmp_path: Path, turn: str = TURN) -> dict:
    return {"session_id": SESSION, "turn_id": turn, "stop_hook_active": False, "cwd": str(tmp_path)}


def _passing_answer(schema: dict) -> dict:
    """Last enum value, because both verdict enums list the passing verdict second."""
    if "notes" in schema["properties"]:
        return {"notes": []}
    fields = schema["properties"]["items"]["items"]["properties"]
    if "language" in fields:
        return {"items": [{"index": 0, "language": fields["language"]["enum"][0]}]}
    return {"items": [{"index": 0, "verdict": fields["verdict"]["enum"][-1], "reason": "Fine."}]}


class _Thread:
    def __init__(self, calls: list[Call], system: str) -> None:
        self.calls, self.system = calls, system

    def run(self, turn: SdkTurn) -> SdkRunResult:
        self.calls.append(Call(self.system, turn.prompt))
        answer = json.dumps(_passing_answer(turn.output_schema))
        return SdkRunResult(answer, (SdkItem("agentMessage"),), {"total_tokens": 1})

    def close(self) -> None:
        return None


class _Session:
    def __init__(self, calls: list[Call]) -> None:
        self.calls = calls

    def account(self) -> SdkAccount:
        return SdkAccount("chatgpt")

    def models(self, *, include_hidden: bool) -> tuple[SdkModel, ...]:
        return (SdkModel(LUNA_MODEL, LUNA_MODEL, not include_hidden, ("high",)),)

    def thread_start(self, start: SdkThreadStart) -> _Thread:
        return _Thread(self.calls, f"{start.base_instructions}\n{start.developer_instructions}")

    def close(self) -> None:
        return None


class _CodexSdk:
    """Stands in for the Codex runtime, because a real Luna call costs a subscription turn."""

    def __init__(self) -> None:
        self.calls: list[Call] = []

    def open(self, _launch: SdkLaunch) -> _Session:
        return _Session(self.calls)

    def retry_on_overload(self, operation: Operation, **_limits: int) -> SdkRunResult:
        return operation()


def _luna(tmp_path: Path, sdk: _CodexSdk) -> LunaJudge:
    return LunaJudge(
        sdk=sdk, runtime_root=tmp_path / "runtime", cache_root=tmp_path / "cache",
        auth_source=tmp_path / "codex-auth.json",
    )


class _Recorder:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []

    def judge(self, request: JudgeRequest) -> JudgeResult:
        self.requests.append(request)
        payload = _passing_answer(judge_contracts.output_schema(request))
        return JudgeResult(payload, "openai-codex", LUNA_MODEL, "high", request.rubric_version, {})


def _fake_claude(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Stands in for the CLI, because a real call costs money and time."""
    bin_dir, log, reply = tmp_path / "bin", tmp_path / "cli-call.json", tmp_path / "cli-reply.json"
    bin_dir.mkdir()
    reply.write_text(json.dumps(CLI_REPLY), encoding="utf-8")
    script = bin_dir / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}, open({str(log)!r}, 'w'))\n"
        f"sys.stdout.write(open({str(reply)!r}).read())\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _sonnet(tmp_path: Path, monkeypatch: MonkeyPatch, state_root: Path) -> list[Call]:
    log = _fake_claude(tmp_path, monkeypatch)
    claude_sonnet.run(_stop_payload(tmp_path), state_root=state_root)
    sent = json.loads(log.read_text(encoding="utf-8"))
    argv = sent["argv"]
    return [Call(argv[argv.index("--system-prompt") + 1], sent["stdin"])]


def _codex_luna(tmp_path: Path, _monkeypatch: MonkeyPatch, state_root: Path) -> list[Call]:
    sdk = _CodexSdk()
    codex_luna.review(_codex_payload(tmp_path), turn_id=TURN, state_root=state_root, provider=_luna(tmp_path, sdk))
    return sdk.calls


def _claude_luna(tmp_path: Path, _monkeypatch: MonkeyPatch, state_root: Path) -> list[Call]:
    sdk = _CodexSdk()
    settings, preset = tmp_path / "settings.json", tmp_path / "preset"
    claude_native.set_preset("luna", settings_path=settings, preset_path=preset)
    claude_luna.run(
        _stop_payload(tmp_path), provider=_luna(tmp_path, sdk), state_root=state_root,
        settings_path=settings, preset_path=preset,
    )
    return sdk.calls


REVIEWERS = pytest.mark.parametrize(
    "reviewer",
    [pytest.param(_sonnet, id="sonnet"), pytest.param(_codex_luna, id="codex-luna"), pytest.param(_claude_luna, id="claude-luna")],
)


@REVIEWERS
def test_reviewers_send_the_shared_instructions_once_in_system_text(tmp_path: Path, monkeypatch: MonkeyPatch, reviewer: Reviewer) -> None:
    state_root = _document_turn(tmp_path)
    block = judge_contracts.reviewer_instructions(config.effective_hook_config({}, str(tmp_path)))

    calls = reviewer(tmp_path, monkeypatch, state_root)

    assert [(call.system.count(block), call.user.count(block)) for call in calls] == [(1, 0)]


def test_the_shared_instructions_state_the_comment_length_budget_of_the_comment_rules(tmp_path: Path) -> None:
    effective = _config(tmp_path, {})

    block = judge_contracts.reviewer_instructions(effective)

    assert _states(block, comment_rules.COMMENT_CHAR_CAP)


@pytest.mark.parametrize(
    ("settings", "cap"),
    [
        pytest.param({}, config.DEFAULTS["list_item_cap"], id="default"),
        pytest.param({"list_item_cap": CUSTOM_LIST_CAP}, CUSTOM_LIST_CAP, id="project"),
    ],
)
def test_the_shared_instructions_state_the_list_item_cap_of_the_effective_config(tmp_path: Path, settings: dict, cap: int) -> None:
    effective = _config(tmp_path, settings)

    block = judge_contracts.reviewer_instructions(effective)

    assert _states(block, cap)


def test_selecting_german_prose_changes_the_shared_instructions(tmp_path: Path) -> None:
    english = _config(tmp_path / "en", {"prose_languages": [prose_language.ENGLISH]})
    german = _config(tmp_path / "de", {"prose_languages": [prose_language.ENGLISH, prose_language.GERMAN]})

    blocks = [judge_contracts.reviewer_instructions(effective) for effective in (english, german)]

    assert blocks[0] != blocks[1]


@REVIEWERS
def test_no_reviewer_states_a_rubric_twice_in_one_call(tmp_path: Path, monkeypatch: MonkeyPatch, reviewer: Reviewer) -> None:
    state_root = _mixed_turn(tmp_path)

    calls = reviewer(tmp_path, monkeypatch, state_root)

    repeated = [name for call in calls for name, rubric in RUBRICS if call.occurrences(rubric) > 1]
    assert (bool(calls), repeated) == (True, [])


def test_codex_luna_sends_the_same_changed_hunks_as_the_claude_luna_preset(tmp_path: Path) -> None:
    state_root = _two_line_edit(tmp_path)
    preset = [build_prompt(request) for request, _rows in claude_luna.stop_request(_stop_payload(tmp_path), state_root)]
    provider = _Recorder()

    codex_luna.review(_codex_payload(tmp_path, "turn-2"), turn_id="turn-2", state_root=state_root, provider=provider)

    assert [build_prompt(request) for request in provider.requests if request.review_kind is ReviewKind.DOCUMENT] == preset


@REVIEWERS
def test_reviewers_still_receive_the_changed_text(tmp_path: Path, monkeypatch: MonkeyPatch, reviewer: Reviewer) -> None:
    state_root = _document_turn(tmp_path)

    calls = reviewer(tmp_path, monkeypatch, state_root)

    assert [CHANGED in call.user for call in calls] == [True]


def test_a_codex_luna_request_reaches_the_luna_worker_unchanged(tmp_path: Path) -> None:
    """Checked apart, because the fake runtime above skips the worker process that real Luna calls cross."""
    provider = _Recorder()
    codex_luna.review(_codex_payload(tmp_path), turn_id=TURN, state_root=_document_turn(tmp_path), provider=provider)
    sent = provider.requests[0]
    launch = SdkLaunch(codex_home=tmp_path / "home", cwd=tmp_path / "cwd", config_overrides=CONFIG_OVERRIDES)
    wire = {key: value for key, value in request_payload(sent, launch).items() if key not in luna_worker.DESCRIPTOR_FIELDS}
    received: list[JudgeRequest] = []

    with redirect_stdout(io.StringIO()):
        luna_worker.main(
            stdin=io.StringIO(json.dumps({**wire, "codex_home": str(launch.codex_home), "cwd": str(launch.cwd)})),
            run=lambda request, _launch: received.append(request) or _Recorder().judge(request),
        )

    assert received == provider.requests


def _language_request(tmp_path: Path) -> JudgeRequest:
    """Built by the language router, because that path is the one that sends LANGUAGE requests to Luna."""
    provider = _Recorder()
    language_verdict.classify([MIXED_PARAGRAPH], provider.judge, tmp_path / "router" / "state")
    return provider.requests[0]


def test_a_luna_language_request_sends_only_the_tool_boundary_as_instructions(tmp_path: Path) -> None:
    """Defaults allow German, so the block also holds the German line that a language check must not get."""
    boundary = judge_contracts.TOOL_BOUNDARY
    block = judge_contracts.reviewer_instructions(config.effective_config()).splitlines()
    others = [line for line in block if line not in boundary and boundary not in line]
    sdk = _CodexSdk()

    language_verdict.classify([MIXED_PARAGRAPH], _luna(tmp_path, sdk).judge, tmp_path / "router" / "state")

    assert [(call.system.count(boundary), [line for line in others if call.occurrences(line)]) for call in sdk.calls] == [(1, [])]


@pytest.mark.parametrize(
    ("suffix", "cached"),
    [pytest.param("", True, id="same sentence"), pytest.param(" Revised.", False, id="revised sentence")],
)
def test_a_luna_language_verdict_is_reused_only_under_the_same_tool_boundary(tmp_path: Path, suffix: str, cached: bool) -> None:
    request = _language_request(tmp_path)
    judge = _luna(tmp_path, _CodexSdk())
    judge.judge(request)

    result = judge.judge(replace(request, instructions=f"{judge_contracts.TOOL_BOUNDARY}{suffix}"))

    assert result.cached is cached
