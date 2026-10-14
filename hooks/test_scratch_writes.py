from __future__ import annotations

from pathlib import Path

import pytest

import pre_bash
from lib import payloads

LONG = "word " * 40


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    scratch = tmp_path / "scratch"
    (project / "docs").mkdir(parents=True)
    scratch.mkdir()
    (scratch / "f.txt").write_text("a\n", encoding="utf-8")
    return project, scratch


def _gate(tmp_path: Path, project: Path, command: str) -> dict:
    payload = {"cwd": str(project), "tool_name": "Bash", "tool_input": {"command": command}}
    config = {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}
    return pre_bash.run(payload, config)


@pytest.mark.parametrize("template", [
    "printf '%s' '{long}' > {scratch}/note.md",
    "printf '%s' '{long}' | tee {scratch}/note.md",
    "sed -i 's/a/b/' {scratch}/f.txt",
    "sed -i '' -e 's/a/b/' {scratch}/f.txt",
    "perl -pi -e 's/a/b/' {scratch}/f.txt",
    "cd {scratch} && sed -i 's/a/b/' f.txt",
    "cd {scratch}; printf '%s' '{long}' > note.md",
])
def test_a_write_whose_every_target_is_scratch_temp_runs(tmp_path: Path, template: str) -> None:
    project, scratch = _dirs(tmp_path)

    assert _gate(tmp_path, project, template.format(long=LONG, scratch=scratch)) == {}


@pytest.mark.parametrize(("template", "rule"), [
    ("sed -i 's/a/b/' docs/f.txt", "inplace_edit_write"),
    ("sed -i 's/a/b/' ~/f.txt", "inplace_edit_write"),
    ("sed -i 's/a/b/' {scratch}/f.txt docs/f.txt", "inplace_edit_write"),
    ("sed -i 's/a/b/w docs/out' {scratch}/f.txt", "inplace_edit_write"),
    ("sed -i 's/a/b/;1e touch x' {scratch}/f.txt", "inplace_edit_write"),
    ("sed -i -f {scratch}/edit.sed {scratch}/f.txt", "inplace_edit_write"),
    ("sed -i 's/a/b/' {scratch}/$NAME", "inplace_edit_write"),
    ("cd {scratch} && sed -i 's/a/b/' ../project/docs/f.txt", "inplace_edit_write"),
    ("cd {scratch} && cd {project} && sed -i 's/a/b/' f.txt", "inplace_edit_write"),
    ("cd {scratch}/missing; sed -i 's/a/b/' f.txt", "inplace_edit_write"),
    ("perl -pi {scratch}/edit.pl {scratch}/f.txt", "inplace_edit_write"),
    ("printf '%s' '{long}' > docs/note.md", "exceeds the"),
    ("cd {scratch} && printf '%s' '{long}' > {project}/docs/note.md", "exceeds the"),
])
def test_a_write_with_a_project_or_unknown_target_still_blocks(tmp_path: Path, template: str, rule: str) -> None:
    project, scratch = _dirs(tmp_path)

    result = _gate(tmp_path, project, template.format(long=LONG, scratch=scratch, project=project))

    assert result.get("decision") == "block"
    assert rule in result["reason"]


@pytest.mark.parametrize("script", [
    "s/a/b/g",
    "s#a#b#i",
    "s{a}{b}gx",
    "tr/a-z/A-Z/",
    "y/ab/ba/",
])
def test_a_perl_scratch_edit_with_one_plain_operator_runs(tmp_path: Path, script: str) -> None:
    project, scratch = _dirs(tmp_path)

    assert _gate(tmp_path, project, f"perl -pi -e '{script}' {scratch}/f.txt") == {}


@pytest.mark.parametrize("edit", [
    """perl -pi -e 'open my $handle, ">", "notes.md"; s/a/b/'""",
    "perl -pi -e 's/a/b/; s/c/d/'",
    "perl -pi -e 's/a/uc $&/e'",
    "perl -pi -e 's/a/b/r'",
    "perl -pi -e 's/a(?{ 1 })/b/'",
    "perl -pi -e 's/a/$ENV{X}/'",
    "perl -pi -e 's/a/@{[ 1 ]}/'",
    "perl -pi -e 's/a/`date`/'",
    "perl -MPOSIX -pi -e 's/a/b/'",
    "perl -pi -e 's/a/b/' -e 's/c/d/'",
    "ruby -pi -e '$_.sub!(/a/, \"b\")'",
])
def test_a_perl_or_ruby_scratch_edit_with_any_other_script_blocks(tmp_path: Path, edit: str) -> None:
    project, scratch = _dirs(tmp_path)

    result = _gate(tmp_path, project, f"{edit} {scratch}/f.txt")

    assert result.get("decision") == "block"
    assert "inplace_edit_write" in result["reason"]


def test_a_scratch_in_place_edit_after_a_leading_cd_is_recorded_as_an_agent_write(tmp_path: Path) -> None:
    project, scratch = _dirs(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Bash", "tool_input": {"command": f"cd {scratch} && sed -i 's/a/b/' f.txt"}}

    assert payloads.edited_paths(payload) == (f"{scratch}/f.txt",)
