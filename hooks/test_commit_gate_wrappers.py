"""Real repos here, because a commit hidden behind a group, a wrapper shell, an abbreviation, or an alias still writes the index git reads."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pre_commit
import pre_tool
from lib import reporting
from testing import make_repo, run_git as git

HOOKS = Path(__file__).resolve().parent
SEED = "This sentence is plain and blocks nothing.\n"
CLEAN = "This sentence is plain and still blocks nothing.\n"
DIRTY = "This sentence uses an em dash " + chr(0x2014) + " which the punctuation family blocks.\n"
MESSAGE = "docs: update the note"
COMMIT_SCRIPT = f"git commit -a -m '{MESSAGE}'\n"
SAFE_SCRIPT = 'printf "ready\\n"\n'
# So that a capped reader still faces a commit past the padding.
PADDING = "# x\n" * 33_000
# So that a gate stuck on a FIFO fails the test instead of hanging it.
FIFO_PROBE = (
    "import json, sys\n"
    "import pre_commit\n"
    "print(json.dumps(pre_commit.run(json.loads(sys.argv[1]), None, ledger_root=sys.argv[2], state_root=sys.argv[3])))\n"
)
FIFO_DEADLINE_SECONDS = 20
Alias = tuple[str, str]


def _repo(tmp_path: Path, staged: str, worktree: str) -> Path:
    repo = make_repo(tmp_path)
    note = repo / "note.md"
    note.write_text(SEED, encoding="utf-8")
    git(repo, "add", "note.md")
    git(repo, "commit", "-q", "-m", "seed")
    note.write_text(staged, encoding="utf-8")
    git(repo, "add", "note.md")
    note.write_text(worktree, encoding="utf-8")
    return repo


def _gate(tmp_path: Path, repo: Path, command: str) -> dict:
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "commit-wrappers",
        "tool_name": "Bash",
        "tool_use_id": "toolu_commit",
        "tool_input": {"command": command},
        "cwd": str(repo),
    }
    return pre_commit.run(payload, None, ledger_root=tmp_path / "ledger", state_root=tmp_path / "state")


def _substituted_heredoc(body: str) -> str:
    return f"git commit -m \"$(cat <<'EOF'\n{body}\nEOF\n)\""


def _recorded_rules(tmp_path: Path) -> set[str]:
    return {row.get("rule") for row in reporting.read_jsonl(reporting.LEDGER_FILENAME, tmp_path / "ledger")}


def _two_commits_and_a_clean_tree(tmp_path: Path) -> Path:
    """Clean, so only a gate that cannot place the commit denies it."""
    repo = _repo(tmp_path, CLEAN, CLEAN)
    git(repo, "commit", "-q", "-m", "second")
    (repo / "sub").mkdir()
    return repo


@pytest.mark.parametrize("command", [
    pytest.param(f"(true); git commit -m '{MESSAGE}'", id="after-a-subshell"),
    pytest.param(f"sh -c \"git commit -m '{MESSAGE}'\"", id="sh-c"),
    pytest.param(f"git status\ngit commit -m '{MESSAGE}'", id="second-line"),
    pytest.param(f"sudo git commit -m '{MESSAGE}'", id="sudo"),
    pytest.param(f"nohup git commit -m '{MESSAGE}'", id="nohup"),
    pytest.param(f"timeout 5 git commit -m '{MESSAGE}'", id="timeout"),
    pytest.param(f"nice git commit -m '{MESSAGE}'", id="nice"),
    pytest.param(f"time git commit -m '{MESSAGE}'", id="time"),
    pytest.param(f"exec git commit -m '{MESSAGE}'", id="exec"),
    pytest.param("git commit -F - <<'EOF'\nDon't\nEOF", id="heredoc-message-with-apostrophe"),
])
def test_a_commit_hidden_in_the_command_is_judged_on_its_staged_finding(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path, DIRTY, DIRTY)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"
    assert "banned_dash" in _recorded_rules(tmp_path)


@pytest.mark.parametrize("command", [
    pytest.param(f"(git add -A); git commit -m '{MESSAGE}'", id="staging-subshell"),
    pytest.param(f"git commit --inc note.md -m '{MESSAGE}'", id="abbreviated-include"),
    pytest.param(f"git commit --interact -m '{MESSAGE}'", id="abbreviated-interactive"),
    pytest.param(f"git commit --patc -m '{MESSAGE}'", id="abbreviated-patch"),
    pytest.param(f"sh -c \"git add -A && git commit -m '{MESSAGE}'\"", id="sh-c-stage-and-commit"),
    pytest.param(f"bash -c 'git commit -a -m \"{MESSAGE}\"'", id="bash-c-commit-all"),
    pytest.param(f"bash <<'EOF'\ngit commit -a -m '{MESSAGE}'\nEOF", id="heredoc-fed-to-bash"),
    pytest.param(f"eval \"git commit -a -m '{MESSAGE}'\"", id="eval"),
    pytest.param(f"git commit \\\n  -a -m '{MESSAGE}'", id="line-continuation"),
    pytest.param(f"$(echo git) commit -a -m '{MESSAGE}'", id="substituted-git"),
    pytest.param(f"cmd=git; \"$cmd\" commit -a -m '{MESSAGE}'", id="variable-git"),
    pytest.param(f"function c {{ git commit -a -m '{MESSAGE}'; }}; c", id="shell-function"),
    pytest.param(f"shopt -s expand_aliases\nalias c='git commit -a -m \"{MESSAGE}\"'\nc", id="shell-alias"),
    pytest.param(f"source <(printf 'git commit -a -m \"{MESSAGE}\"\\n')", id="sourced-process-substitution"),
])
def test_a_hidden_commit_that_takes_content_from_outside_the_index_is_denied(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path, SEED, DIRTY)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


def _scripted_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path, SEED, DIRTY)
    (repo / "scripts").mkdir()
    chain = {f"chain{number}.sh": f"source chain{number + 1}.sh\n" for number in range(6)}
    scripts = {
        "action.sh": COMMIT_SCRIPT, "scripts/action.sh": COMMIT_SCRIPT, "outer.sh": "source action.sh\n",
        "safe.sh": SAFE_SCRIPT, "safe script.sh": SAFE_SCRIPT, "fresh.sh": SAFE_SCRIPT, "mentions.sh": 'echo "git commit"\n',
        "runner.sh": '"$@"\n', "exec-runner.sh": 'exec "$@"\n', "echo-runner.sh": 'echo "$@"\n',
        "oversized.sh": PADDING + COMMIT_SCRIPT, "oversized-safe.sh": PADDING + SAFE_SCRIPT,
        **chain, "chain6.sh": "source action.sh\n",
    }
    for name, text in scripts.items():
        (repo / name).write_text(text, encoding="utf-8")
    (repo / "link.sh").symlink_to("action.sh")
    (repo / "stale-link.sh").symlink_to("safe.sh")
    (repo / "dirlink").symlink_to("scripts", target_is_directory=True)
    return repo


@pytest.mark.parametrize("command", [
    pytest.param("bash action.sh", id="script"),
    pytest.param("bash link.sh", id="symlinked-script"),
    pytest.param("bash dirlink/action.sh", id="script-under-a-symlinked-directory"),
    pytest.param("bash -- action.sh", id="script-after-double-dash"),
    pytest.param("bash outer.sh", id="one-level-source"),
    pytest.param("bash oversized.sh", id="oversized-script"),
    pytest.param("bash missing.sh commit", id="missing-script-with-a-commit-argument"),
    pytest.param("bash < action.sh", id="stdin-redirect"),
    pytest.param("< action.sh bash", id="leading-stdin-redirect"),
    pytest.param("bash -s < action.sh", id="stdin-redirect-with-s"),
    pytest.param("bash 3< action.sh <&3", id="duplicated-descriptor"),
    pytest.param("bash /dev/fd/3 3< action.sh", id="dev-fd-path"),
    pytest.param("bash <(cat action.sh)", id="process-substitution"),
    pytest.param("source <(cat action.sh)", id="sourced-process-substitution"),
    pytest.param("bash chain0.sh", id="source-chain-past-the-nesting-bound"),
    pytest.param(f"bash runner.sh git commit -a -m '{MESSAGE}'", id="positional-arguments"),
    pytest.param(f"bash exec-runner.sh git commit -a -m '{MESSAGE}'", id="exec-positional-arguments"),
    pytest.param('script=action.sh; bash "$script"', id="script-path-in-a-variable"),
])
def test_a_commit_run_through_a_script_is_denied(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param(f"printf 'git commit -a -m \"{MESSAGE}\"\\n' > fresh.sh; bash fresh.sh", id="overwritten-script"),
    pytest.param("cp action.sh fresh.sh; bash fresh.sh", id="copied-script"),
    pytest.param(f"printf 'git commit -a -m \"{MESSAGE}\"\\n' > new.sh; bash new.sh", id="created-script"),
    pytest.param("ln -sf action.sh stale-link.sh; bash stale-link.sh", id="retargeted-symlink"),
    pytest.param("printf 'x' >> safe.sh && bash safe.sh", id="appended-script"),
])
def test_a_script_changed_earlier_in_the_same_command_is_denied(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param("bash -x safe.sh; bash safe.sh", id="traced-run"),
    pytest.param("bash --norc safe.sh; bash safe.sh", id="long-option-holding-an-n"),
    pytest.param("node safe.sh; bash safe.sh", id="node-run-without-check"),
])
def test_a_script_executed_earlier_in_the_same_command_is_denied(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param("bash -n safe.sh && bash safe.sh", id="bash-n"),
    pytest.param("sh -xn safe.sh; bash safe.sh", id="n-in-a-short-option-cluster"),
    pytest.param("zsh -n safe.sh && bash safe.sh", id="zsh-n"),
    pytest.param("dash -n safe.sh && bash safe.sh", id="dash-n"),
    pytest.param("ksh -n safe.sh && bash safe.sh", id="ksh-n"),
    pytest.param("node --check safe.sh && bash safe.sh", id="node-check"),
    pytest.param("node -c safe.sh && bash safe.sh", id="node-c"),
])
def test_a_parse_only_check_before_running_the_script_passes(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") is None


def _pre_tool(repo: Path, command: str) -> dict:
    return pre_tool.run({"session_id": "parse-only", "cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": command}})


@pytest.mark.parametrize("command", [
    pytest.param('for s in safe.sh action.sh; do bash -n "$s"; done', id="documented-syntax-loop"),
    pytest.param('bash -n "$S"', id="bash-n"),
    pytest.param("sh -n $S", id="sh-n-unquoted"),
    pytest.param('sh -xn "$S"', id="n-in-a-short-option-cluster"),
])
def test_a_parse_only_run_of_a_script_path_held_in_a_variable_passes(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    response = _pre_tool(repo, command)

    assert response.get("decision") is None, response.get("reason")


@pytest.mark.parametrize("command", [
    pytest.param('bash "$S"', id="plain-run"),
    pytest.param('bash -x "$S"', id="traced-run"),
    pytest.param('bash +n "$S"', id="plus-n-turns-parse-only-off"),
])
def test_a_run_of_a_script_path_held_in_a_variable_still_blocks(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    response = _pre_tool(repo, command)

    assert response.get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param("bash safe.sh", id="script"),
    pytest.param('bash -- "safe script.sh"', id="quoted-path"),
    pytest.param("bash < safe.sh", id="stdin-redirect"),
    pytest.param("bash oversized-safe.sh", id="oversized-script"),
    pytest.param("bash mentions.sh", id="script-that-echoes-the-words"),
    pytest.param(f"bash echo-runner.sh git commit -a -m '{MESSAGE}'", id="positional-arguments-echoed"),
])
def test_a_script_that_does_not_commit_passes(tmp_path: Path, command: str) -> None:
    repo = _scripted_repo(tmp_path)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") is None


def test_a_script_path_that_is_a_fifo_gets_an_answer_without_a_writer(tmp_path: Path) -> None:
    repo = _repo(tmp_path, SEED, DIRTY)
    os.mkfifo(repo / "input.pipe")
    payload = {"hook_event_name": "PreToolUse", "session_id": "fifo", "tool_name": "Bash", "tool_input": {"command": "bash input.pipe"}, "cwd": str(repo)}
    arguments = [json.dumps(payload), str(tmp_path / "ledger"), str(tmp_path / "state")]

    done = subprocess.run(
        [sys.executable, "-c", FIFO_PROBE, *arguments], cwd=HOOKS, env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True, text=True, timeout=FIFO_DEADLINE_SECONDS, check=False,
    )

    assert done.returncode == 0, done.stderr


def _other_index_holding_the_worktree(repo: Path) -> None:
    """Built through git itself, because the gate must face the index file the commit would really read."""
    env = {**os.environ, "GIT_INDEX_FILE": str(repo / "x")}
    subprocess.run(["git", "read-tree", "HEAD"], cwd=repo, env=env, check=True, capture_output=True)
    subprocess.run(["git", "add", "note.md"], cwd=repo, env=env, check=True, capture_output=True)


@pytest.mark.parametrize("command", [
    pytest.param(f"GIT_INDEX_FILE=x git commit -m '{MESSAGE}'", id="inline"),
    pytest.param(f"env GIT_INDEX_FILE=x git commit -m '{MESSAGE}'", id="env"),
    pytest.param(f"GIT_INDEX_FILE=x git --no-pager commit -m '{MESSAGE}'", id="inline-after-a-git-option"),
    pytest.param(f"export GIT_INDEX_FILE=x; git commit -m '{MESSAGE}'", id="export"),
])
def test_a_commit_from_another_index_file_is_denied(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path, CLEAN, DIRTY)
    _other_index_holding_the_worktree(repo)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param(f"env -C sub git commit -m '{MESSAGE}'", id="env-chdir"),
    pytest.param(f"echo note.md | xargs git commit -m '{MESSAGE}'", id="xargs"),
    pytest.param(f"find . -name note.md -exec git commit -m '{MESSAGE}' {{}} +", id="find-exec"),
    pytest.param('git rebase -x "git commit --amend -a --no-edit" HEAD~1', id="rebase-exec"),
])
def test_a_commit_the_gate_cannot_place_is_denied(tmp_path: Path, command: str) -> None:
    repo = _two_commits_and_a_clean_tree(tmp_path)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param("git log --grep commit", id="log-search"),
    pytest.param('echo "git commit" > notes.txt', id="echoed-text"),
])
def test_a_command_that_only_names_a_commit_passes(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path, DIRTY, DIRTY)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") is None


@pytest.mark.parametrize(("alias", "command"), [
    pytest.param(("ci", "commit -a"), f"git ci -m '{MESSAGE}'", id="commit-all-alias"),
    pytest.param(("save", "!git add -A && git commit -m wip"), "git save", id="shell-alias"),
])
def test_an_alias_that_commits_outside_the_index_is_denied(tmp_path: Path, alias: Alias, command: str) -> None:
    repo = _repo(tmp_path, SEED, DIRTY)
    git(repo, "config", f"alias.{alias[0]}", alias[1])

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") == "block"


def test_an_alias_that_does_not_commit_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, SEED, DIRTY)
    git(repo, "config", "alias.st", "status")

    result = _gate(tmp_path, repo, "git st")

    assert result.get("decision") is None


@pytest.mark.parametrize("command", [
    pytest.param("git commit -m \"$(cat <<'EOF'\nUpdate the note\n\nDon't drop quoted text.\nEOF\n)\"", id="substituted-heredoc"),
    pytest.param("git commit -F - <<'EOF'\nUpdate the note\n\nDon't drop quoted text.\nEOF", id="heredoc-on-stdin"),
    pytest.param(_substituted_heredoc(f"{MESSAGE}\n\nDon't drop quoted text."), id="substituted-heredoc-with-a-conventional-subject"),
])
def test_a_heredoc_commit_message_over_a_clean_index_passes(tmp_path: Path, command: str) -> None:
    repo = _repo(tmp_path, CLEAN, CLEAN)

    result = _gate(tmp_path, repo, command)

    assert result.get("decision") is None


def test_a_substituted_heredoc_message_that_breaks_a_rule_still_blocks(tmp_path: Path) -> None:
    repo = _repo(tmp_path, CLEAN, CLEAN)

    result = _gate(tmp_path, repo, _substituted_heredoc(f"{MESSAGE}\n\nThe body keeps a dash {chr(0x2014)} here."))

    assert result.get("decision") == "block"
    assert "banned_dash" in _recorded_rules(tmp_path)


def test_an_option_name_inside_the_commit_message_does_not_count_as_that_option(tmp_path: Path) -> None:
    repo = _repo(tmp_path, CLEAN, DIRTY)

    result = _gate(tmp_path, repo, 'git commit -m "fix --all flag"')

    assert result.get("decision") is None
