"""Because find and xargs pick their targets at run time, a delete passes only when the gate can see every file it would remove."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lib import protected
from test_tests_policy_gate import project, shell

ARRANGED = (
    "project/build/cache.pyc", "project/pkg/__pycache__/a.cpython-311.pyc", "project/notes.md",
    "project/list.txt", "project/tests/test_x.py", "scratch/cache.pyc",
)


@pytest.fixture(autouse=True)
def _isolated_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)
    (tmp_path / "home" / ".adw").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


@pytest.fixture
def unreadable_folder(tmp_path: Path) -> Iterator[Path]:
    locked = tmp_path / "scratch" / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0)
    yield locked
    locked.chmod(0o700)


def arranged_project(tmp_path: Path, extra: tuple = ()) -> Path:
    for name in (*ARRANGED, *extra):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    return project(tmp_path / "project", tests="deny")


@pytest.mark.parametrize("command", [
    pytest.param("find . -name '*.pyc' -delete", id="R2-6-project"),
    pytest.param("find TMP/scratch -type f -name '*.pyc' -delete", id="R2-6-absolute-scratch"),
    pytest.param("printf '%s\\0' TMP/scratch/cache.pyc | xargs -0 rm --", id="R2-7-null-framed"),
    pytest.param("printf notes.md | xargs rm --", id="R2-7-plain"),
    pytest.param("printf notes.md | xargs -I{} rm -- {}", id="R2-7-replace"),
])
def test_a_delete_whose_every_target_is_ordinary_passes(tmp_path: Path, command: str) -> None:
    cwd = arranged_project(tmp_path)
    assert shell(cwd, command.replace("TMP", str(tmp_path))).get("decision") != "block"


@pytest.mark.parametrize("arrangement", [
    pytest.param((("project/tests/__pycache__/test_x.cpython-311.pyc",), "find . -name '*.pyc' -delete"),
                 id="R2-6-test-cache"),
    pytest.param((("project/.adw/cache.pyc",), "find . -name '*.pyc' -delete"), id="R2-6-project-state"),
    pytest.param((("home/.adw/cache.pyc",), "find \"$HOME/.adw\" -name '*.pyc' -delete"), id="R2-6-home-state"),
    pytest.param(((), "cat list.txt | xargs rm --"), id="R2-7-unknown-producer"),
    pytest.param(((), "printf 'notes.md\\ntests/test_x.py' | xargs rm --"), id="R2-7-line-framed-test"),
    pytest.param(((), "printf '%s\\0' tests/test_x.py | xargs -0 rm --"), id="R2-7-null-framed-test"),
])
def test_a_delete_that_reaches_a_protected_or_unknown_file_is_denied(tmp_path: Path, arrangement: tuple) -> None:
    extra, command = arrangement
    assert shell(arranged_project(tmp_path, extra), command).get("decision") == "block"


def test_a_find_delete_over_a_folder_it_cannot_read_is_denied(tmp_path: Path, unreadable_folder: Path) -> None:
    cwd = arranged_project(tmp_path)
    command = f"find {unreadable_folder.parent} -type f -name '*.pyc' -delete"
    assert shell(cwd, command).get("decision") == "block"
