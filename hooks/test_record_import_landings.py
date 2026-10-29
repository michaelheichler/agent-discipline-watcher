"""Because a landing in ignored scratch is imported only when none of its words can come from the agent, a file URL copy or a capture that can carry agent text must face the post-run gate like any write."""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

import record
from test_tests_policy_gate import isolated
from testing import make_repo, run_git

AGENT_CODE = "# Returns the total value\nvalue = 1\n"


def _scratch_copy(tmp_path: Path, destination: str) -> tuple[Path, str]:
    """Copied ahead of the record run, because the gate scans the file the command left behind."""
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    (repo / "scratch").mkdir()
    mine = repo / "scratch" / "mine.py"
    mine.write_text(AGENT_CODE, encoding="utf-8")
    (repo / destination).write_text(AGENT_CODE, encoding="utf-8")
    return repo, f"curl -o {destination} file://{mine}"


@pytest.mark.parametrize("destination", [
    pytest.param("app.py", id="into-the-project"),
    pytest.param("scratch/app.py", id="into-ignored-scratch"),
])
def test_a_file_url_copy_of_the_agents_scratch_file_blocks_on_its_findings(tmp_path: Path, destination: str) -> None:
    repo, command = _scratch_copy(tmp_path, destination)
    payload = {"session_id": "t19", "cwd": str(repo), "tool_name": "Bash", "turn_id": "turn",
               "tool_use_id": "use", "tool_input": {"command": command},
               "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}

    response = record.run(payload, isolated(tmp_path))

    assert (response.get("decision"), destination in response.get("reason", "")) == ("block", True)


DASHED_CAPTURE = "zigbee2mqtt/Bad - Spiegel/availability online\n"
COMMITTED = {".gitignore": ".build/\n", "tools/scan.py": "print('scan')\n", "tools/seen.txt": "seen\n", "notes.md": "notes\n"}
MAKEFILE = {"Makefile": "print:\n\t@date\n"}
PACKAGE = {"package.json": '{"scripts": {"gen": "date"}}\n'}
EDITED_PACKAGE = {"package.json": '{"scripts": {"gen": "cat notes.md"}}\n'}


class Layout(NamedTuple):
    """Files committed before the run and files written after the commit, because only committed, unchanged files count as a producer."""

    committed: dict[str, str] | None = None
    uncommitted: dict[str, str] | None = None


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")


def _captured_run(tmp_path: Path, command: str, destination: str = ".build/x.txt", layout: Layout = Layout()) -> dict:
    """Seeded with a spaced-hyphen line, because only a finding shows whether the capture counts as the agent's text."""
    repo = make_repo(tmp_path)
    _write(repo, {**COMMITTED, **(layout.committed or {})})
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "start")
    _write(repo, {**(layout.uncommitted or {}), destination: DASHED_CAPTURE})
    payload = {"session_id": "t19", "cwd": str(repo), "tool_name": "Bash", "turn_id": "turn",
               "tool_use_id": "use", "tool_input": {"command": command},
               "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}
    return record.run(payload, isolated(tmp_path))


@pytest.mark.parametrize(("command", "layout"), [
    pytest.param("ssh hub 'cat /srv/topics' > .build/x.txt", Layout(), id="ssh-capture"),
    pytest.param("ssh hub journalctl -u x > .build/x.txt", Layout(), id="ssh-remote-journal"),
    pytest.param("ffmpeg -i in.mp4 -f null - 2> .build/x.txt", Layout(), id="ffmpeg-stderr-log"),
    pytest.param("python3 tools/scan.py config > .build/x.txt", Layout(), id="committed-script-file"),
    pytest.param("journalctl -u hub --no-pager | tail -n 200 | tee .build/x.txt", Layout(), id="passthrough-stages"),
    pytest.param("docker logs c > .build/x.txt", Layout(), id="docker-logs"),
    pytest.param("make print > .build/x.txt", Layout(committed=MAKEFILE), id="make-with-committed-makefile"),
    pytest.param("npm run gen > .build/x.txt", Layout(committed=PACKAGE), id="npm-run-with-committed-package"),
])
def test_an_external_tool_output_captured_into_ignored_scratch_reports_as_inherited(tmp_path: Path, command: str, layout: Layout) -> None:
    response = _captured_run(tmp_path, command, layout=layout)
    context = response.get("hookSpecificOutput", {}).get("additionalContext", "")

    assert (response.get("decision"), ".build/x.txt" in context) == (None, True)


@pytest.mark.parametrize(("command", "layout"), [
    pytest.param("python3 tools/scan.py config > .build/x.txt", Layout(uncommitted={"tools/scan.py": "print(1)\n"}),
                 id="script-edited-after-commit"),
    pytest.param("python3 tools/gen.py > .build/x.txt", Layout(uncommitted={"tools/gen.py": "print(1)\n"}),
                 id="untracked-script"),
    pytest.param("python3 -m gen > .build/x.txt", Layout(), id="python-module-other-than-pytest"),
    pytest.param("ssh hub cat < notes.md > .build/x.txt", Layout(), id="input-redirect-to-remote-host"),
    pytest.param("ssh localhost cat < notes.md > .build/x.txt", Layout(), id="input-redirect-to-localhost"),
    pytest.param("ssh localhost cat /srv/notes.md > .build/x.txt", Layout(), id="localhost"),
    pytest.param("ssh 127.0.0.1 cat /srv/notes.md > .build/x.txt", Layout(), id="loopback-address"),
    pytest.param("ssh ::1 cat /srv/notes.md > .build/x.txt", Layout(), id="ipv6-loopback"),
    pytest.param("ssh hub awk 'BEGIN{print \"x\"}' > .build/x.txt", Layout(), id="remote-command-not-a-reader"),
    pytest.param("ssh hub 'cat a; cat b' > .build/x.txt", Layout(), id="shell-operator-in-remote-command"),
    pytest.param("docker run --rm alpine cat /w/x > .build/x.txt", Layout(), id="docker-run"),
    pytest.param("podman exec c cat /w/x > .build/x.txt", Layout(), id="podman-exec"),
    pytest.param("kubectl exec pod -- cat /w/x > .build/x.txt", Layout(), id="kubectl-exec"),
    pytest.param("gh api --input notes.md x > .build/x.txt", Layout(), id="gh-api-input"),
    pytest.param("gh api -f body=x repos/o/r/issues > .build/x.txt", Layout(), id="gh-api-field"),
    pytest.param("make -f gen.mk print > .build/x.txt", Layout(uncommitted={"gen.mk": MAKEFILE["Makefile"]}),
                 id="make-named-makefile"),
    pytest.param("make print > .build/x.txt", Layout(uncommitted=MAKEFILE), id="make-with-uncommitted-makefile"),
    pytest.param("npm run gen > .build/x.txt", Layout(uncommitted=PACKAGE), id="npm-run-with-uncommitted-package"),
    pytest.param("npm run gen > .build/x.txt", Layout(committed=PACKAGE, uncommitted=EDITED_PACKAGE),
                 id="npm-run-with-edited-package"),
    pytest.param("npx cowsay hi > .build/x.txt", Layout(), id="npx-unknown-tool"),
    pytest.param('ffmpeg -i in.mp4 -metadata comment="$(cat notes.md)" -f ffmetadata - > .build/x.txt', Layout(),
                 id="command-substitution-into-a-local-tool"),
])
def test_a_capture_whose_producer_can_print_agent_text_blocks(tmp_path: Path, command: str, layout: Layout) -> None:
    response = _captured_run(tmp_path, command, layout=layout)

    assert (response.get("decision"), ".build/x.txt" in response.get("reason", "")) == ("block", True)


@pytest.mark.parametrize(("command", "destination"), [
    pytest.param("ssh hub 'cat /srv/topics' > tools/seen.txt", "tools/seen.txt", id="tracked-destination"),
    pytest.param("ssh hub 'cat /srv/topics' >> .build/x.txt", ".build/x.txt", id="append"),
    pytest.param("ssh hub uptime | echo x > .build/x.txt", ".build/x.txt", id="echo-in-pipeline"),
    pytest.param("ssh hub \"echo 'a - b'\" > .build/x.txt", ".build/x.txt", id="echo-on-the-remote-end"),
    pytest.param("ssh hub python3 -c 'print(1)' > .build/x.txt", ".build/x.txt", id="inline-python-on-the-remote-end"),
    pytest.param("printf 'a - b' | ssh hub cat > .build/x.txt", ".build/x.txt", id="printf-in-pipeline"),
    pytest.param("ssh hub cat <<EOF > .build/x.txt\nBad - Spiegel\nEOF", ".build/x.txt", id="heredoc"),
    pytest.param("python3 -c 'print(1)' > .build/x.txt", ".build/x.txt", id="inline-python"),
    pytest.param("python3 < tools/scan.py > .build/x.txt", ".build/x.txt", id="interpreter-reading-stdin"),
    pytest.param("ssh hub uptime | cat notes.md > .build/x.txt", ".build/x.txt", id="later-stage-cats-local-file"),
    pytest.param("ssh hub uptime | grep Bad notes.md > .build/x.txt", ".build/x.txt", id="later-stage-greps-local-file"),
])
def test_a_capture_that_can_carry_the_agents_own_text_blocks(tmp_path: Path, command: str, destination: str) -> None:
    response = _captured_run(tmp_path, command, destination)

    assert (response.get("decision"), destination in response.get("reason", "")) == ("block", True)
