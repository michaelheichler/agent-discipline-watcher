import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import record
import stop
from lib import blocker_state
from lib.scanner import scan_all


RULE = '''---
description: Keep the implementations aligned.
globs:
  - "crates/**/*.rs"
  - "js/model/**"
  - "verifier/**"
alwaysApply: false
---
Update the matching implementation in `crates/` and run the parity check.
Keep the fixture version synchronized with the reference model.
'''


@pytest.mark.parametrize("suffix", [".mdc", ".MDC"])
def test_cursor_rules_have_markdown_semantics(suffix: str) -> None:
    assert scan_all("rules/parity" + suffix, RULE) == []
    body = RULE + "The rule is this: a body colon still blocks.\n"
    findings = scan_all("rules/parity" + suffix, body, {"english": False})
    assert {(row["rule"], row["line"]) for row in findings} == {("prose_colon", 11)}


def test_post_edit_and_stop_accept_cursor_rule_frontmatter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OMPCODE", "1")
    monkeypatch.delenv("ADW_CODEX_HOOK", raising=False)
    target = tmp_path / "parity.mdc"
    target.write_text(RULE, encoding="utf-8")
    config = {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state"), "baseline": "none"}
    payload = {"session_id": "cursor-rule", "cwd": str(tmp_path), "tool_name": "Edit", "tool_input": {"file_path": str(target)}}
    assert record.run(payload, config) == {}
    blocker_state.touch_paths("cursor-rule", "", [str(target)], config["state_root"])
    assert stop.run({"session_id": "cursor-rule", "cwd": str(tmp_path), "hook_event_name": "Stop"}, config) == {}


def test_stop_rechecks_an_unchanged_rule_after_a_prior_comment_denial(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OMPCODE", "1")
    monkeypatch.delenv("ADW_CODEX_HOOK", raising=False)
    target = tmp_path / "parity.mdc"
    target.write_text(RULE, encoding="utf-8")
    config = {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}
    blocker_state.touch_paths("prior-rule", "", [str(target)], config["state_root"])
    blocker_state.set_pending("prior-rule", "", str(target), "Old what_comment denial", config["state_root"])
    response = stop.run({"session_id": "prior-rule", "cwd": str(tmp_path), "hook_event_name": "Stop"}, config)
    assert response == {}
    assert target.read_text(encoding="utf-8") == RULE


def test_shell_entrypoint_accepts_mdc_through_the_omp_lifecycle(tmp_path: Path) -> None:
    target = tmp_path / "parity.mdc"
    target.write_text(RULE, encoding="utf-8")
    environment = {"HOME": str(tmp_path), "PATH": os.defpath, "OMPCODE": "1", "ADW_PYTHON": sys.executable}
    payload = {
        "session_id": "mdc-shell", "cwd": str(tmp_path), "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": RULE},
    }
    for event in ("PreToolUse", "PostToolUse", "Stop"):
        result = subprocess.run(
            [str(Path(__file__).with_name("run.sh")), event],
            input=json.dumps({**payload, "hook_event_name": event}), text=True,
            capture_output=True, check=False, env=environment,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {}, (event, result.stdout)
