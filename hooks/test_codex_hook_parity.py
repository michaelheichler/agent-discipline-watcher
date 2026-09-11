import json
import re
import tomllib
from pathlib import Path

import pytest

import record
import stop
from lib import journal, reporting, session_state
from lib.judge_contracts import ReviewKind
from test_task4_codex import Provider, _result
from test_codex_hooks_merge import run_merge


HOOKS = Path(__file__).parent
SUPPORTED_EVENTS = {
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "SubagentStart", "SubagentStop", "Stop", "SessionEnd",
}


@pytest.fixture(autouse=True)
def isolated_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reporting, "_reports_dir", lambda: tmp_path / "reports")


def _command_groups(config: dict, event: str) -> list[dict]:
    return [
        {**group, "hooks": [hook for hook in group["hooks"] if hook["type"] == "command"]}
        for group in config["hooks"].get(event, [])
        if any(hook["type"] == "command" for hook in group["hooks"])
    ]


@pytest.mark.parametrize("event", sorted(SUPPORTED_EVENTS))
def test_codex_covers_the_claude_command_events_and_matchers(event: str) -> None:
    claude = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    codex = json.loads((HOOKS / "codex-hooks.json").read_text(encoding="utf-8"))
    expected = _command_groups(claude, event)
    actual = _command_groups(codex, event)

    assert actual
    assert [group.get("matcher", "") for group in actual] == [
        group.get("matcher", "") for group in expected
    ]


def test_codex_json_and_toml_register_the_same_hooks() -> None:
    manifest = json.loads((HOOKS / "codex-hooks.json").read_text(encoding="utf-8"))
    snippet = tomllib.loads((HOOKS / "codex-config.snippet.toml").read_text(encoding="utf-8"))

    assert manifest["hooks"] == snippet["hooks"]
    assert set(manifest["hooks"]) == SUPPORTED_EVENTS


@pytest.mark.parametrize("tool", ["Bash", "MultiEdit", "NotebookEdit", "mcp__files__write"])
def test_codex_pretool_routes_supported_mutations(tool: str) -> None:
    manifest = json.loads((HOOKS / "codex-hooks.json").read_text(encoding="utf-8"))
    matching = [
        group for group in _command_groups(manifest, "PreToolUse")
        if re.search(group.get("matcher", ""), tool)
    ]

    assert len(matching) == 1


def test_post_write_candidates_reach_stop_with_the_host_turn_id(tmp_path: Path) -> None:
    source = tmp_path / "note.md"
    source.write_text("The archive contains seven records.\n", encoding="utf-8")
    config = {"state_root": str(tmp_path / "state"), "ledger_root": str(tmp_path / "ledger")}
    session_state.write_state("session", {"turn_id": "turn-1"}, config["state_root"])
    payload = {
        "session_id": "session", "turn_id": "host-turn", "cwd": str(tmp_path),
        "tool_name": "Write", "tool_use_id": "write", "tool_input": {"file_path": str(source)},
    }
    provider = Provider(_result(ReviewKind.DOCUMENT))

    assert record.run(payload, config).get("decision") != "block"
    assert stop.run({**payload, "stop_hook_active": False}, config, provider=provider) == {}
    assert len(provider.calls) == 1
    assert {row["turn_id"] for row in journal.read("session", state_root=config["state_root"])} == {"host-turn"}


def test_installer_preserves_unrelated_handlers_sharing_a_watcher_group(tmp_path: Path) -> None:
    destination = tmp_path / "hooks.json"
    other = {"type": "command", "command": "storybloq hook-status --client codex", "timeout": 12}
    destination.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": 'ADW_CODEX_HOOK=1 "/old/hooks/run.sh" Stop'}, other,
    ]}]}}), encoding="utf-8")

    run_merge(destination)
    first = destination.read_text(encoding="utf-8")
    run_merge(destination)
    merged = json.loads(destination.read_text(encoding="utf-8"))
    handlers = [handler for group in merged["hooks"]["Stop"] for handler in group["hooks"]]

    assert other in handlers
    assert first == destination.read_text(encoding="utf-8")
    assert len(handlers) == 2
