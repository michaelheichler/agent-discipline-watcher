"""Because the shell writes to the path a variable expands to, every gate must judge that path and not its spelling."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
import record
from lib import protected, tests_policy
from test_tests_policy_gate import blocked_by, isolated, project, shell
from testing import make_repo

PROSE = "We leverage a rich tapestry of utilities."
PROTECTED_WRITES = pytest.mark.parametrize("protected_write", [
    (".agent-discipline.json", """'{"tests":"allow"}'""", "config_seal"),
    ("tests/test_fonts.py", "hello", tests_policy.RULE),
], ids=["config", "test"])


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


def after_run(cwd: Path, command: str) -> dict:
    payload = {"session_id": "t19", "cwd": str(cwd), "tool_name": "Bash", "turn_id": "turn",
               "tool_use_id": "use", "tool_input": {"command": command},
               "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}
    return record.run(payload, isolated(cwd))


@pytest.mark.parametrize("destination", ['"$M"', "$M", '"${M}"'])
@PROTECTED_WRITES
def test_a_variable_redirect_faces_the_gate_of_its_expansion(tmp_path: Path, destination: str, protected_write: tuple) -> None:
    target, body, rule = protected_write
    command = f"M={target}; printf {body} > {destination}"
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), rule)


def test_a_variable_delete_target_faces_the_state_gate(tmp_path: Path) -> None:
    assert blocked_by(shell(project(tmp_path, tests="deny"), 'X=.adw; rm -rf "$X"'), "state_deletion")


def test_a_variable_redirect_scans_the_file_it_expands_to(tmp_path: Path) -> None:
    cwd = project(tmp_path)
    (cwd / "notes.md").write_text(PROSE, encoding="utf-8")

    reason = after_run(cwd, 'M=notes.md; printf hello > "$M"').get("reason", "")

    assert "unscannable_file" not in reason
    assert "inflated_diction" in reason


def test_a_substituted_redirect_is_not_reported_as_an_unreadable_file(tmp_path: Path) -> None:
    cwd = project(tmp_path)
    (cwd / ".build" / "restore").mkdir(parents=True)
    (cwd / ".build" / "restore" / "notes.md").write_text("hello", encoding="utf-8")

    response = after_run(cwd, 'f=notes.md; printf hello > ".build/restore/$(basename $f)"')

    assert "unscannable_file" not in response.get("reason", "")


def test_a_substituted_redirect_target_blocks_before_the_run(tmp_path: Path) -> None:
    response = shell(project(tmp_path), 'f=notes.md; printf hello > ".build/restore/$(basename $f)"')
    assert blocked_by(response, "dynamic_write_target")


def test_a_single_quoted_dollar_target_is_a_known_destination(tmp_path: Path) -> None:
    response = shell(project(tmp_path), "M=notes; printf hello > '$M.md'")
    assert not blocked_by(response, "dynamic_write_target")


def test_a_single_quoted_dollar_stays_a_literal_file_name(tmp_path: Path) -> None:
    cwd = project(tmp_path)
    (cwd / "$M.md").write_text(PROSE, encoding="utf-8")
    (cwd / "notes.md").write_text("hello", encoding="utf-8")

    response = after_run(cwd, "M=notes; printf hello > '$M.md'")

    assert "inflated_diction" in response.get("reason", "")


def test_an_expanding_write_over_the_cap_still_hits_the_cap(tmp_path: Path) -> None:
    body = "A" * (pre_bash.BASH_WRITE_CAP + 1)

    response = shell(project(tmp_path, tests="deny"), f'M=notes.md; printf "%s" "{body}" > "$M"')

    assert response.get("decision") == "block"


@PROTECTED_WRITES
def test_a_later_literal_protected_write_keeps_its_gate(tmp_path: Path, protected_write: tuple) -> None:
    target, body, rule = protected_write
    command = f'M=notes.md; printf hello > "$M"; printf {body} > {target}'
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), rule)


@pytest.mark.parametrize("command", [
    pytest.param("M=notes.md; printf -v \"$(printf '\\115')\" %s .agent-discipline.json; printf x > \"$M\"",
                 id="A1-printf-v"),
    pytest.param("M=notes.md; read \"$(printf '\\115')\" <<< .agent-discipline.json; printf x > \"$M\"", id="A1-read"),
    pytest.param("M=notes.md; declare \"$(printf '\\115')\"=.agent-discipline.json; printf x > \"$M\"",
                 id="A1-declare"),
])
def test_a_variable_a_computed_name_may_reassign_is_not_proven(tmp_path: Path, command: str) -> None:
    assert shell(project(tmp_path, tests="deny"), command).get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param('M=notes.md\nprintf x > "$M"', id="A8-next-line"),
    pytest.param('M=notes.md; printf "%s\\n" M; printf x > "$M"', id="A8-name-as-data"),
    pytest.param('M=notes.md; printf x > "$M" # M is the output', id="A8-name-in-comment"),
    pytest.param('M=notes.md; N=$M; printf x > "$N"', id="A8-copied"),
    pytest.param('export M=notes.md; printf x > "$M"', id="A8-export"),
    pytest.param('readonly M=notes.md; printf x > "$M"', id="A8-readonly"),
    pytest.param('declare M=notes.md; printf x > "$M"', id="A8-declare"),
    pytest.param('M=notes.md; printf -v N %s x; printf x > "$M"', id="A1-other-name"),
    pytest.param('M=notes.md; printf x > "$M"; M=other.md', id="R2-8-later-assignment"),
])
def test_a_variable_that_provably_names_an_ordinary_file_passes(tmp_path: Path, command: str) -> None:
    assert shell(project(tmp_path, tests="deny"), command).get("decision") != "block"


@PROTECTED_WRITES
def test_a_later_assignment_does_not_move_an_earlier_protected_write(tmp_path: Path, protected_write: tuple) -> None:
    target, body, rule = protected_write
    command = f'M={target}; printf {body} > "$M"; M=notes.md'
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), rule)


def test_an_earlier_write_is_scanned_at_the_path_it_had_then(tmp_path: Path) -> None:
    cwd = project(tmp_path)
    (cwd / "notes.md").write_text(PROSE, encoding="utf-8")

    response = after_run(cwd, 'M=notes.md; printf x > "$M"; M=other.md')

    assert "inflated_diction" in response.get("reason", "")


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("command", [
    pytest.param('M=.; M+=agent-discipline.json; printf x > "$M"', id="R2-1-stdout"),
    pytest.param('M=.; M+=agent-discipline.json; printf x 2>"$M"', id="R2-1-stderr"),
])
def test_an_appended_variable_is_not_judged_by_its_first_value(tmp_path: Path, command: str, policy: str) -> None:
    assert shell(project(tmp_path, tests=policy), command).get("decision") == "block"


def test_an_appended_variable_does_not_report_its_first_value_after_the_run(tmp_path: Path) -> None:
    response = after_run(project(tmp_path), 'M=.; M+=agent-discipline.json; printf x > "$M"')
    assert "unscannable_file" not in response.get("reason", "")


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("command", [
    pytest.param('mktemp() { printf .agent-discipline.json; }; out=$(mktemp); printf x > "$out"', id="R2-2-mktemp"),
    pytest.param('pwd() { printf .agent-discipline.json; }; out=$(pwd); printf x > "$out"', id="R2-2-pwd"),
])
def test_a_shadowed_command_substitution_is_not_trusted(tmp_path: Path, command: str, policy: str) -> None:
    assert shell(project(tmp_path, tests=policy), command).get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param('out=$(mktemp); printf x > "$out"', id="R2-2-file"),
    pytest.param('out=$(mktemp -d); printf x > "$out/file.md"', id="R2-2-folder"),
])
def test_a_mktemp_write_names_no_invented_file(command: str) -> None:
    assert pre_bash.write_paths(command) == []


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("command", [
    pytest.param('out=$(mktemp); printf x > "$out"', id="R2-2-file"),
    pytest.param('out=$(mktemp -d); printf x > "$out/file.md"', id="R2-2-folder"),
])
def test_a_write_to_a_name_mktemp_picks_at_run_time_is_denied(tmp_path: Path, command: str, policy: str) -> None:
    assert blocked_by(shell(project(make_repo(tmp_path), tests=policy), command), "dynamic_write_target")


@pytest.mark.parametrize("command", [
    pytest.param('cd "$(git rev-parse --show-toplevel)" && printf x > notes.md', id="repo-root"),
    pytest.param('cd "$(pwd)" && printf x > notes.md', id="current-folder"),
])
def test_a_well_known_substitution_resolves_and_passes(tmp_path: Path, command: str) -> None:
    assert shell(project(make_repo(tmp_path), tests="deny"), command).get("decision") != "block"


@pytest.mark.parametrize("command", [
    pytest.param('cd "$(git rev-parse --show-toplevel)" && printf x > notes.md', id="repo-root"),
    pytest.param('cd "$(pwd)" && printf x > notes.md', id="current-folder"),
])
def test_a_well_known_substitution_scans_the_file_it_resolves_to(tmp_path: Path, command: str) -> None:
    cwd = project(make_repo(tmp_path))
    (cwd / "notes.md").write_text(PROSE, encoding="utf-8")

    response = after_run(cwd, command)

    assert "inflated_diction" in response.get("reason", "")


@pytest.mark.parametrize("command", [
    pytest.param('out=$(mktemp -p .); printf x > "$out"', id="project-folder"),
    pytest.param('out=$(mktemp tests/test_XXXX.py); printf x > "$out"', id="test-name"),
])
def test_a_mktemp_with_a_path_template_is_denied(tmp_path: Path, command: str) -> None:
    assert shell(project(make_repo(tmp_path), tests="deny"), command).get("decision") == "block"
