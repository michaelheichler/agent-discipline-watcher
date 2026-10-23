"""Because a shell reaches a protected file through many verbs and descriptors, each route must face the gate its destination faces."""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
import pre_tool
from lib import protected, tests_policy
from test_bash_variable_redirects import PROSE, after_run
from test_tests_policy_gate import blocked_by, isolated, project, shell

DENIED_ROUTES = [
    pytest.param("printf x 2>.agent-discipline.json", id="A2-stderr-config"),
    pytest.param("printf x 2>tests/test_x.py", id="A2-stderr-test"),
    pytest.param('printf x 2>"$HOME/.adw/report.json"', id="A2-stderr-state"),
    pytest.param("printf x > $'\\x2eagent-discipline.json'", id="A3-ansi-c-config"),
    pytest.param("M=.agent-discipline.json; eval 'printf x > \"$M\"'", id="A4-eval-config"),
    pytest.param("echo .agent-discipline.json | xargs cp source", id="A5-xargs-copy-config"),
    pytest.param("printf tests/test_x.py | xargs cp source", id="A5-xargs-copy-test"),
    pytest.param("printf tests/test_x.py | xargs -I{} sh -c 'printf x > \"{}\"'", id="A5-xargs-shell-test"),
    pytest.param('echo "$HOME/.adw" | xargs rm -rf', id="A5-xargs-remove-state"),
    pytest.param("find . -name .agent-discipline.json -delete", id="A5-find-delete-config"),
    pytest.param("find tests -type f -delete", id="A5-find-delete-tests"),
    pytest.param('find . -name "test_*.py" -delete', id="A5-find-delete-test-names"),
    pytest.param('find . -path "./tests/*" -exec rm {} +', id="A5-find-exec-tests"),
    pytest.param("find . -name .adw -exec rm -rf {} +", id="A5-find-exec-project-state"),
    pytest.param('find "$HOME/.adw" -type f -delete', id="A5-find-delete-state"),
    pytest.param('find "$HOME" -name .adw -exec rm -rf {} +', id="A5-find-exec-state"),
    pytest.param("rsync source .agent-discipline.json", id="A6-rsync-config"),
    pytest.param('rsync --delete empty/ "$HOME/.adw/"', id="A6-rsync-state"),
    pytest.param("cat source | sponge .agent-discipline.json", id="A6-sponge-config"),
    pytest.param("awk 'BEGIN {print \"x\" > \".agent-discipline.json\"}'", id="A6-awk-config"),
    pytest.param("touch tests/test_x.py", id="A6-touch-test"),
    pytest.param("ln -sf .agent-discipline.json alias; printf x > alias", id="A7-new-link-config"),
    pytest.param('ln -sf "$HOME/.adw/report.json" alias; printf x > alias', id="A7-new-link-state"),
    pytest.param("python3 <<< \"open('x','w').write('y')\"", id="A11-here-string-write"),
    pytest.param("printf .agent-discipline.json | xargs rg --pre rm needle", id="R2-4-xargs-rg-pre"),
    pytest.param("printf .agent-discipline.json | xargs rg --pre=rm needle", id="R2-4-xargs-rg-pre-joined"),
    pytest.param("find . -name .agent-discipline.json -exec rg --pre rm needle {} +", id="R2-4-find-rg-pre"),
]
HARMLESS_ROUTES = [
    pytest.param("printf x 2>&1", id="A2-stderr-to-stdout"),
    pytest.param("printf x 2>/dev/null", id="A2-stderr-discarded"),
    pytest.param("printf x > $'notes.md'", id="A3-ansi-c-plain"),
    pytest.param("eval 'printf x > notes.md'", id="A4-eval-plain"),
    pytest.param('find . -name "*.md"', id="A5-find-list"),
    pytest.param("xargs grep foo", id="A5-xargs-read"),
    pytest.param("find . -type f | xargs wc -l", id="A5-find-xargs-read"),
    pytest.param("touch notes.md", id="A6-touch-plain"),
    pytest.param("awk '{print $1}' file", id="A6-awk-read"),
    pytest.param("ln -sf notes.md alias; printf x > alias", id="A7-new-link-plain"),
    pytest.param('python3 <<< "print(1)"', id="A11-here-string-read"),
    pytest.param("curl -I https://example.invalid/", id="R2-3-curl-head"),
    pytest.param("wget --spider https://example.invalid/", id="R2-3-wget-spider"),
    pytest.param("sort notes.md", id="R2-3-sort-to-stdout"),
    pytest.param("curl -o release.tar.gz https://example.invalid/release.tar.gz", id="R2-3-download-archive"),
    pytest.param("curl -o notes.md https://example.invalid/notes.md", id="R2-3-download-prose"),
    pytest.param('find . -name "*.py" -print', id="R2-4-find-print"),
    pytest.param("find . -type f -print0 | xargs -0 grep -n needle", id="R2-4-find-xargs-grep"),
    pytest.param('find . -name "*.py" -exec rg needle {} +', id="R2-4-find-rg"),
    pytest.param("printf notes.md | xargs rg needle", id="R2-4-xargs-rg"),
    pytest.param("awk '{print $1}' README.md", id="R2-4-awk-read"),
    pytest.param("awk 'BEGIN {print 1}'", id="R2-4-awk-begin"),
]
OUTPUT_FLAG_FORMS = {
    "curl-o": "curl -o {dest} https://example.invalid/data",
    "curl-o-joined": "curl -o{dest} https://example.invalid/data",
    "curl-output": "curl --output {dest} https://example.invalid/data",
    "curl-output-joined": "curl --output={dest} https://example.invalid/data",
    "wget-O": "wget -O {dest} https://example.invalid/data",
    "wget-O-joined": "wget -O{dest} https://example.invalid/data",
    "wget-output-document": "wget --output-document {dest} https://example.invalid/data",
    "wget-output-document-joined": "wget --output-document={dest} https://example.invalid/data",
    "sort-o": "sort -o {dest} notes.md",
    "sort-o-joined": "sort -o{dest} notes.md",
    "sort-output": "sort --output {dest} notes.md",
    "sort-output-joined": "sort --output={dest} notes.md",
}
WATCHER_FILES = {"config": ".agent-discipline.json", "state": '"$HOME/.adw/report.json"'}
TEST_FILE = "tests/test_x.py"
MERGE_INTO_NOTES = "git merge-file notes.md a b"
CODE = "# Returns the total value\nvalue = 1\n"
OUTPUT_FLAG_WATCHER_WRITES = [
    pytest.param(form.format(dest=dest), id=f"R2-3-{form_id}-{dest_id}")
    for form_id, form in OUTPUT_FLAG_FORMS.items()
    for dest_id, dest in WATCHER_FILES.items()
]
OUTPUT_FLAG_TEST_WRITES = [
    pytest.param(form.format(dest=TEST_FILE), id=f"R2-3-{form_id}-test") for form_id, form in OUTPUT_FLAG_FORMS.items()
]
SCANNED_TARGETS = {
    "code": ("src/app.py", CODE, "what_comment"),
    "prose": ("guide.md", PROSE, "inflated_diction"),
}
OUTPUT_FLAG_SCANS = [
    pytest.param((form.format(dest=path), path, body, rule), id=f"R2-3-{form_id}-{kind}")
    for form_id, form in OUTPUT_FLAG_FORMS.items()
    for kind, (path, body, rule) in SCANNED_TARGETS.items()
]
CODE_WRITES_SCANNED_AFTER_THE_RUN = [
    *[pytest.param((form.format(dest=TEST_FILE), TEST_FILE), id=f"R2-3-{form_id}-test")
      for form_id, form in OUTPUT_FLAG_FORMS.items()],
    pytest.param(("curl -o src/app.py https://example.invalid/data", "src/app.py"), id="R2-3-source-output-flag"),
    pytest.param(("curl https://example.invalid/data > src/app.py", "src/app.py"), id="R2-3-source-redirect"),
]


@pytest.fixture(autouse=True)
def _isolated_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)
    home = tmp_path / "home"
    (home / ".adw").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))


def route_project(tmp_path: Path, policy: str = "deny") -> Path:
    cwd = tmp_path / "project"
    (cwd / "tests").mkdir(parents=True)
    (cwd / "src").mkdir()
    (cwd / "empty").mkdir()
    for name in ("tests/test_x.py", "source", "notes.md", "file", "README.md", "src/app.py"):
        (cwd / name).write_text("x\n", encoding="utf-8")
    return project(cwd, tests=policy)


def tool_answer(cwd: Path, command: str) -> dict:
    payload = {"session_id": "t19", "cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": command}}
    return pre_tool.run(payload, isolated(cwd))


@pytest.mark.parametrize("command", DENIED_ROUTES)
def test_a_route_to_a_protected_destination_is_denied(tmp_path: Path, command: str) -> None:
    assert shell(route_project(tmp_path), command).get("decision") == "block"


@pytest.mark.parametrize("command", HARMLESS_ROUTES)
def test_a_route_to_an_ordinary_destination_passes(tmp_path: Path, command: str) -> None:
    assert shell(route_project(tmp_path), command).get("decision") != "block"


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("command", OUTPUT_FLAG_WATCHER_WRITES)
def test_an_output_flag_onto_a_watcher_file_is_denied_under_any_policy(tmp_path: Path, command: str, policy: str) -> None:
    assert shell(route_project(tmp_path, policy), command).get("decision") == "block"


@pytest.mark.parametrize("command", OUTPUT_FLAG_TEST_WRITES)
def test_an_output_flag_onto_a_test_is_denied_when_tests_are_denied(tmp_path: Path, command: str) -> None:
    assert shell(route_project(tmp_path, "deny"), command).get("decision") == "block"


@pytest.mark.parametrize("write", CODE_WRITES_SCANNED_AFTER_THE_RUN)
def test_a_generated_write_into_code_passes_when_tests_are_allowed(tmp_path: Path, write: tuple) -> None:
    command, _ = write
    assert tool_answer(route_project(tmp_path, "allow"), command).get("decision") != "block"


@pytest.mark.parametrize("write", CODE_WRITES_SCANNED_AFTER_THE_RUN)
def test_a_generated_write_into_code_names_its_file_for_the_journal(tmp_path: Path, write: tuple) -> None:
    command, target = write
    cwd = route_project(tmp_path, "allow")

    named = {(cwd / path).resolve() for path in pre_bash.write_paths(command, str(cwd))}

    assert (cwd / target).resolve() in named


@pytest.mark.parametrize("write", CODE_WRITES_SCANNED_AFTER_THE_RUN)
def test_a_generated_write_into_code_is_scanned_after_the_run(tmp_path: Path, write: tuple) -> None:
    command, target = write
    cwd = route_project(tmp_path, "allow")
    (cwd / target).write_text(CODE, encoding="utf-8")

    response = after_run(cwd, command)

    assert "what_comment" in response.get("reason", "")


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("scan", OUTPUT_FLAG_SCANS)
def test_an_output_flag_destination_is_scanned_after_the_run(tmp_path: Path, scan: tuple, policy: str) -> None:
    command, target, body, rule = scan
    cwd = route_project(tmp_path, policy)
    (cwd / target).write_text(body, encoding="utf-8")

    response = after_run(cwd, command)

    assert rule in response.get("reason", "")


@pytest.mark.parametrize("policy", ["deny", "allow"])
def test_a_download_whose_file_name_cannot_be_proven_is_denied(tmp_path: Path, policy: str) -> None:
    response = shell(route_project(tmp_path, policy), "wget https://example.invalid/")
    assert blocked_by(response, "dynamic_write_target")


def test_a_write_through_an_existing_link_faces_the_config_seal(tmp_path: Path) -> None:
    cwd = route_project(tmp_path)
    (cwd / "alias").symlink_to(cwd / ".agent-discipline.json")
    assert blocked_by(shell(cwd, "printf x > alias"), "config_seal")


@pytest.mark.parametrize("policy", ["deny", "allow"])
@pytest.mark.parametrize("command", [
    pytest.param(f"git merge-file {dest} a b", id=dest_id) for dest_id, dest in WATCHER_FILES.items()
])
def test_a_merge_into_a_watcher_file_is_denied_under_any_policy(tmp_path: Path, command: str, policy: str) -> None:
    assert tool_answer(route_project(tmp_path, policy), command).get("decision") == "block"


@pytest.mark.parametrize("command", [
    pytest.param("git merge-file -p notes.md a b > .agent-discipline.json", id="printed-into-config"),
    pytest.param("git merge-file --stdout notes.md a b > tests/test_y.py", id="printed-into-test"),
])
def test_a_printed_merge_redirected_onto_a_protected_file_is_denied(tmp_path: Path, command: str) -> None:
    assert tool_answer(route_project(tmp_path, "deny"), command).get("decision") == "block"


def test_a_merge_into_a_test_is_denied_when_tests_are_denied(tmp_path: Path) -> None:
    response = tool_answer(route_project(tmp_path, "deny"), "git merge-file tests/test_x.py a b")
    assert blocked_by(response, tests_policy.RULE)


@pytest.mark.parametrize("command", [
    pytest.param("git merge-file -p tests/test_x.py a b", id="short-flag"),
    pytest.param("git merge-file --stdout tests/test_x.py a b", id="long-flag"),
])
def test_a_merge_that_only_prints_passes(tmp_path: Path, command: str) -> None:
    assert tool_answer(route_project(tmp_path, "deny"), command).get("decision") != "block"


def test_a_merge_into_an_ordinary_file_passes(tmp_path: Path) -> None:
    assert tool_answer(route_project(tmp_path), MERGE_INTO_NOTES).get("decision") != "block"


def test_a_merge_into_an_ordinary_file_names_it_for_the_journal(tmp_path: Path) -> None:
    cwd = route_project(tmp_path)

    named = {(cwd / path).resolve() for path in pre_bash.write_paths(MERGE_INTO_NOTES, str(cwd))}

    assert (cwd / "notes.md").resolve() in named


def test_a_merge_into_an_ordinary_file_is_scanned_after_the_run(tmp_path: Path) -> None:
    cwd = route_project(tmp_path)
    (cwd / "notes.md").write_text(PROSE, encoding="utf-8")

    response = after_run(cwd, MERGE_INTO_NOTES)

    assert "inflated_diction" in response.get("reason", "")
