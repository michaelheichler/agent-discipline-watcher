"""Preserve user hook options because ADW migration must not rewrite unrelated policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


MERGER = Path(__file__).resolve().parent / "merge-codex-config.py"


def migrate(path, root) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(MERGER), "--config", str(path),
                           "--skill-dir", str(root / "skill"), "--strip-only"],
                          check=False, capture_output=True, text=True,
                          env={**os.environ, "HOME": str(root)}, cwd=root)


def test_inline_migration_preserves_every_unrelated_toml_value(tmp_path) -> None:
    path = tmp_path / "config.toml"
    command = 'echo {hello} "quoted"'
    text = '[hooks]\nStop = [{ command = "agent-discipline-watcher/hooks/run.sh Stop" }, '
    text += '{ command = ' + json.dumps(command) + ', timeout = 13, enabled = true, '
    text += 'labels = ["a", "b"], options = { retries = 2, strict = false } }]\n'
    path.write_text(text, encoding="utf-8")

    result = migrate(path, tmp_path)

    assert result.returncode == 0
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["hooks"]["Stop"] == [{"hooks": [{
        "type": "command", "command": command, "timeout": 13, "enabled": True,
        "labels": ["a", "b"], "options": {"retries": 2, "strict": False},
    }]}]


@pytest.mark.parametrize("item", [
    pytest.param("17", id="non-table"),
    pytest.param('{ command = 17 }', id="non-string-command"),
    pytest.param('{ command = "echo ok", hooks = [] }', id="nested-hooks"),
    pytest.param('{ command = "echo ok", when = 2026-11-09 }', id="unsupported-date"),
])
def test_unsupported_inline_migrations_fail_without_rewriting_user_config(tmp_path, item) -> None:
    path = tmp_path / "config.toml"
    original = f'[hooks]\nStop = [{{ command = "agent-discipline-watcher/run.sh" }}, {item}]\n'
    path.write_text(original, encoding="utf-8")

    result = migrate(path, tmp_path)

    assert result.returncode != 0
    assert path.read_text(encoding="utf-8") == original
