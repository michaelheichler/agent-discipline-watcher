"""Heredoc bodies through the Bash gate, because only the bodies a shell runs are commands."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
from lib import host, protected, tests_policy
from test_tests_policy_gate import blocked_by, isolated, project, shell
from testing import make_repo, run_git as git

SKIPPED_GATE = "git commit --no-verify"
INHERITED_DEBT = "# Returns the total value\nvalue = 1\n"


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)
    monkeypatch.delenv(host.CODEX_ENV, raising=False)


@pytest.mark.parametrize("command", [
    "cat > /tmp/x.py <<'EOF'\necho hi > .agent-discipline.json\nEOF",
    f"tee /tmp/y.txt <<'EOF'\n{SKIPPED_GATE}\nEOF",
    f"cat <<'EOF'\n{SKIPPED_GATE}\nEOF",
    f"cat <<EOF\n{SKIPPED_GATE}\nEOF",
    f"echo \"it's\" && cat <<EOF > /tmp/n.txt\n{SKIPPED_GATE}\nEOF",
], ids=["redirect-in-cat-body", "commit-in-tee-body", "quoted-delimiter-to-stdout", "bare-delimiter-to-stdout",
        "apostrophe-in-earlier-quotes"])
def test_a_literal_body_cat_or_tee_reads_is_not_judged_as_a_command(tmp_path: Path, command: str) -> None:
    assert shell(project(tmp_path, tests="deny"), command) == {}


@pytest.mark.parametrize("command", [
    f"cat '<<EOF'\n{SKIPPED_GATE}\nEOF",
    f"cat \"<<EOF\"\n{SKIPPED_GATE}\nEOF",
    f"cat \\<<EOF\n{SKIPPED_GATE}\nEOF",
    f"bash <<EOF\n{SKIPPED_GATE}\nEOF",
    f"bash <<'EOF'\n{SKIPPED_GATE}\nEOF",
    f"cat <<'EOF' | sh\n{SKIPPED_GATE}\nEOF",
    f"source <(cat <<'EOF'\n{SKIPPED_GATE}\nEOF\n)",
    f"cat > /tmp/x <<EOF\n$({SKIPPED_GATE} -m x)\nEOF",
    f"cat > /tmp/x <<'EOF'\nhello\nEOF\n{SKIPPED_GATE} -m x",
], ids=["single-quoted-operator", "double-quoted-operator", "escaped-operator", "shell-reads-bare-heredoc",
        "shell-reads-heredoc", "heredoc-piped-to-sh", "process-substitution", "unquoted-expansion", "after-delimiter"])
def test_a_skipped_commit_gate_the_shell_will_run_still_blocks(tmp_path: Path, command: str) -> None:
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), "commit_gate_bypass")


def test_a_heredoc_with_a_spaced_quoted_delimiter_still_has_its_target_content_scanned(tmp_path: Path) -> None:
    command = "cat << 'EOF' > notes.md\nWe leverage a rich tapestry of utilities.\nEOF"
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), "inflated_diction")


@pytest.mark.parametrize(("command", "rule"), [
    ("cat > .agent-discipline.json <<EOF\n{}\nEOF", "state_mutation"),
    ("python3 <<EOF\nopen('.agent-discipline.json', 'w').write('{}')\nEOF", "interpreter_heredoc_write"),
    ("cat > tests/test_a.py <<'EOF'\ndef test_total():\n    assert 1 + 1 == 2\nEOF", tests_policy.RULE),
], ids=["protected-target", "interpreter-body", "test-target"])
def test_a_heredoc_target_or_interpreter_body_keeps_its_check(tmp_path: Path, command: str, rule: str) -> None:
    assert blocked_by(shell(project(tmp_path, tests="deny"), command), rule)


def test_an_allowed_bash_write_puts_inherited_debt_in_agent_context(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "module.py").write_text(INHERITED_DEBT, encoding="utf-8")
    git(repo, "add", "module.py")
    git(repo, "commit", "-q", "-m", "seed")
    command = f"cat > module.py <<'EOF'\n{INHERITED_DEBT}other = 2\nEOF"
    payload = {"session_id": "t40", "cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": command}}
    output = pre_bash.run(payload, isolated(tmp_path))["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert "what_comment" in output["additionalContext"]
