"""Listed by route, because each one reaches the user policy."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
from lib import protected, vendor

LAUNCHER = vendor.REPO_ROOT / "bin" / "adw-config"


def decision(command: str) -> dict:
    return pre_bash.run({"tool_input": {"command": command}}, {})


@pytest.mark.parametrize("command", [
    "adw-config tests allow",
    "~/.adw/bin/adw-config tests deny",
    "/opt/any/bin/adw-config family english off",
    "'adw-config' tests allow",
    "adw\\-config tests allow",
    "true && adw-config tests allow",
    "env adw-config tests allow",
    "env -i PATH=/bin adw-config tests allow",
    "FOO=1 adw-config tests allow",
    "command adw-config family prose off",
    "exec adw-config tests allow",
    "nohup adw-config tests allow",
    "sudo -u me adw-config tests allow",
    "sh adw-config tests allow",
    "sh -c 'adw-config tests allow'",
    "bash -c \"adw-config family prose off\"",
    "bash <<'EOF'\nadw-config tests allow\nEOF",
    "eval adw-config tests allow",
    "eval 'adw-config tests allow'",
    "echo tests allow | xargs adw-config",
    "$CFG tests allow",
    "$CFG prose-languages en",
    "find . -exec adw-config prose-languages en ;",
    "\"$(command -v adw-config)\" tests allow",
    "adw-config purge",
    "PYTHONPATH=hooks python3 -m lib.adw_config tests allow",
    "python3 hooks/lib/adw_config.py tests allow",
    "ln -s ~/.adw/bin/adw-config ./cfg",
    "echo 'adw-config tests allow' | sh",
    "env -S 'adw-config tests allow'",
    "find . -exec adw-config tests allow ;",
    "timeout 5 adw-config tests allow",
    "nice adw-config tests allow",
    "{ adw-config tests allow; }",
    "if true; then adw-config tests allow; fi",
    "x=$(adw-config tests allow)",
])
def test_a_mutating_route_to_adw_config_is_blocked(command: str) -> None:
    result = decision(command)
    assert result.get("decision") == "block", result
    assert "config_seal" in result["reason"]


def test_a_renamed_symlink_to_the_launcher_is_blocked(tmp_path: Path) -> None:
    link = tmp_path / "polcfg"
    link.symlink_to(LAUNCHER)
    result = decision(f"{link} tests allow")
    assert result.get("decision") == "block", result
    assert "config_seal" in result["reason"]


@pytest.mark.parametrize("command", [
    "adw-config status",
    "~/.adw/bin/adw-config status",
    "adw-config",
    "echo 'adw-config tests allow'",
    "grep -n adw-config README.md",
    "PYTHONPATH=hooks python3 -m lib.adw_config status",
])
def test_status_and_mentions_pass(command: str) -> None:
    assert "config_seal" not in decision(command).get("reason", "")


def write_rules(path: Path, content: str) -> list[str]:
    return [row["rule"] for row in protected.path_findings(str(path), {}, None, content)]


def test_a_config_write_that_changes_tests_is_sealed(tmp_path: Path) -> None:
    target = tmp_path / ".agent-discipline.json"
    target.write_text('{"tests": "deny"}', encoding="utf-8")
    assert write_rules(target, '{"tests": "allow"}') == ["config_seal"]
    assert write_rules(target, '{"max_rows": 3}') == ["config_seal"]


def test_a_config_write_that_keeps_tests_passes(tmp_path: Path) -> None:
    target = tmp_path / ".agent-discipline.json"
    target.write_text('{"tests": "deny"}', encoding="utf-8")
    assert write_rules(target, '{"tests": "deny", "max_rows": 3}') == []


def test_a_new_config_cannot_set_tests(tmp_path: Path) -> None:
    assert write_rules(tmp_path / ".agent-discipline.json", '{"tests": "deny"}') == ["config_seal"]
