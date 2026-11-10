"""Because commit substitutions carry prose, their heredoc bodies must survive shell parsing."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

import pre_commit
import pre_tool
from lib import commit_command, host, protected, tests_policy
from test_tests_policy_gate import blocked_by, isolated
from testing import make_repo


BODY_CASES = [
    pytest.param('Preserve the quoted ")" marker.', id="quoted-close"),
    pytest.param("Don't remove the parser.", id="apostrophe"),
    pytest.param('Preserve the unmatched " marker.', id="unmatched-double"),
]
LITERAL_CASES = [
    *BODY_CASES,
    pytest.param("Preserve the `marker` text.", id="backticks"),
    pytest.param("Preserve the $( marker.", id="literal-substitution"),
]
HEREDOC_CASES = [
    pytest.param("'EOF'", body.values[0], id=f"single-{body.id}")
    for body in LITERAL_CASES
] + [
    pytest.param('"EOF"', body.values[0], id=f"double-{body.id}")
    for body in LITERAL_CASES
] + [
    pytest.param("EOF", body.values[0], id=f"bare-{body.id}")
    for body in BODY_CASES
]


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)
    monkeypatch.delenv(host.CODEX_ENV, raising=False)


@pytest.fixture(params=[pre_tool.run, pre_commit.run], ids=["dispatcher", "commit-gate"])
def gate(request: pytest.FixtureRequest) -> Callable:
    return request.param


def substitution(delimiter: str, body: str, operator: str, trailing: str) -> str:
    prefix = "\t" * (operator == "<<-")
    content = prefix + body.replace("\n", "\n" + prefix)
    return f'git commit -m "$(cat {operator}{delimiter}{trailing}\n{content}\n{prefix}EOF\n)"'


def payload(repo: Path, command: str) -> dict:
    return {"session_id": "heredoc-commit", "cwd": str(repo), "tool_name": "Bash",
            "tool_input": {"command": command}}


@pytest.mark.parametrize(("delimiter", "body"), HEREDOC_CASES)
@pytest.mark.parametrize("operator", [pytest.param("<<", id="plain"), pytest.param("<<-", id="tabs")])
@pytest.mark.parametrize("trailing", [pytest.param("", id="none"), pytest.param(" ", id="space"),
                                     pytest.param("\t", id="tab")])
def test_clean_commit_heredoc_prose_passes_both_gates(
    tmp_path: Path, gate: Callable, delimiter: str, body: str, operator: str, trailing: str,
) -> None:
    repo = make_repo(tmp_path)
    command = substitution(delimiter, body, operator, trailing)

    result = gate(payload(repo, command), isolated(tmp_path))

    assert result == {}


@pytest.mark.parametrize(("delimiter", "body"), HEREDOC_CASES)
@pytest.mark.parametrize("operator", [pytest.param("<<", id="plain"), pytest.param("<<-", id="tabs")])
@pytest.mark.parametrize("trailing", [pytest.param("", id="none"), pytest.param(" ", id="space"),
                                     pytest.param("\t", id="tab")])
def test_commit_heredoc_prose_still_blocks_semicolons(
    tmp_path: Path, gate: Callable, delimiter: str, body: str, operator: str, trailing: str,
) -> None:
    repo = make_repo(tmp_path)
    command = substitution(delimiter, body + "\n\nWe ship it; it works.", operator, trailing)

    result = gate(payload(repo, command), isolated(tmp_path))

    assert blocked_by(result, "prose_semicolon")


@pytest.mark.parametrize(("delimiter", "body"), HEREDOC_CASES)
@pytest.mark.parametrize("operator", [pytest.param("<<", id="plain"), pytest.param("<<-", id="tabs")])
@pytest.mark.parametrize("trailing", [pytest.param("", id="none"), pytest.param(" ", id="space"),
                                     pytest.param("\t", id="tab")])
def test_git_receives_literal_heredoc_prose_without_trailing_newlines(
    tmp_path: Path, delimiter: str, body: str, operator: str, trailing: str,
) -> None:
    command = substitution(delimiter, body + "\n\n", operator, trailing)

    calls = commit_command.git_calls(command, tmp_path)

    assert len(calls) == 1
    assert calls[0].verb == "commit"
    assert calls[0].args[-1] == body


@pytest.mark.parametrize("command", [
    pytest.param('git commit -m "$(cat <<\'EOF\'\nPreserve the parser.\nEOF\n)', id="outer-quote"),
    pytest.param('git commit -m "$(cat <<\'EOF\'\nPreserve the parser.\nEOF\n"', id="substitution-close"),
    pytest.param('git commit -m "$(cat <<EOF "\nPreserve the parser.\nEOF\n)"', id="inner-quote"),
])
def test_malformed_commit_substitutions_remain_blocked(
    tmp_path: Path, gate: Callable, command: str,
) -> None:
    repo = make_repo(tmp_path)

    result = gate(payload(repo, command), isolated(tmp_path))

    assert result.get("decision") == "block"


@pytest.mark.parametrize(("command", "rule"), [
    pytest.param('git commit -m "$(cat <<EOF\n$(git commit --no-verify)\nEOF\n)"',
                 "commit_gate_bypass", id="unquoted-expansion"),
    pytest.param('cat > tests/test_parser.py <<\'EOF\'\ndef test_parser():\n    assert parse(1) == 1\nEOF',
                 tests_policy.RULE, id="test-target"),
    pytest.param('cat > .agent-discipline.json <<\'EOF\'\n{}\nEOF',
                 "state_mutation", id="protected-target"),
])
def test_heredoc_execution_and_write_guards_remain_blocked(
    tmp_path: Path, command: str, rule: str,
) -> None:
    repo = make_repo(tmp_path)

    result = pre_tool.run(payload(repo, command), isolated(tmp_path))

    assert blocked_by(result, rule)
