"""Through split_edited_paths, because only the imported list keeps a downloaded file from blocking on findings nobody here wrote."""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from lib import import_landings, payloads, temp_copies
from testing import make_repo

BODY = "Plain text.\n"
IGNORED = "scratch"
NOT_IGNORED = "work"
REMOTE_DOWNLOADS = [
    pytest.param("curl -o page.md https://example.com/page", id="curl-output-flag"),
    pytest.param("curl -sSL https://example.com/page -o page.md", id="curl-output-flag-last"),
    pytest.param("wget -O page.md http://example.com/page", id="wget-output-flag"),
    pytest.param("curl https://example.com/page > page.md", id="curl-redirect"),
    pytest.param("wget -qO- https://example.com/page > page.md", id="wget-redirect"),
    pytest.param("curl -o page.md ftp://example.com/page", id="curl-ftp"),
]
EXTRACTIONS = [
    pytest.param("tar -xf bundle.tar", id="tar"),
    pytest.param("unzip bundle.zip", id="unzip"),
]
REMOTE_CLONES = [
    pytest.param("git clone https://example.com/repo.git", id="https-default-directory"),
    pytest.param("git clone --depth 1 https://example.com/other.git repo", id="https-named-directory"),
    pytest.param("git clone ssh://git@example.com/team/repo.git", id="ssh-url"),
    pytest.param("git clone git://example.com/repo.git", id="git-url"),
    pytest.param("git clone git@example.com:team/repo.git", id="scp-style"),
]


def _folder(tmp_path: Path, name: str) -> Path:
    """Inside a repo that ignores scratch, because only a path git ignores may hold imported text."""
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text(f"{IGNORED}/\n", encoding="utf-8")
    folder = repo / name
    folder.mkdir()
    return folder


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BODY, encoding="utf-8")
    return path


def _archives(cwd: Path) -> Path:
    """Extracted ahead of the split, because only a file present after the run counts as landed."""
    guide = _write(cwd / "staging" / "guide.md")
    with tarfile.open(cwd / "bundle.tar", "w") as archive:
        archive.add(guide, arcname="docs/guide.md")
    with zipfile.ZipFile(cwd / "bundle.zip", "w") as archive:
        archive.write(guide, arcname="docs/guide.md")
    return _write(cwd / "docs" / "guide.md")


def _clone(cwd: Path, extra_files: int = 0) -> Path:
    _write(cwd / "repo" / ".git" / "HEAD")
    for index in range(extra_files):
        _write(cwd / "repo" / "pages" / f"page{index}.md")
    return _write(cwd / "repo" / "README.md")


def _split(cwd: Path, command: str, authored: frozenset[str] = frozenset()) -> tuple[tuple[str, ...], tuple[str, ...]]:
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    return payloads.split_edited_paths(payload, authored)


def _resolved(cwd: Path, paths: tuple[str, ...]) -> list[Path]:
    return [(cwd / path).resolve() for path in paths]


@pytest.mark.parametrize("command", REMOTE_DOWNLOADS)
def test_a_remote_download_into_ignored_scratch_lands_as_imported(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, IGNORED)
    page = _write(cwd / "page.md")

    assert _split(cwd, command) == ((), (str(page),))


@pytest.mark.parametrize("command", REMOTE_DOWNLOADS)
def test_a_remote_download_into_a_path_git_does_not_ignore_stays_written(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, NOT_IGNORED)
    page = _write(cwd / "page.md")

    written, imported = _split(cwd, command)

    assert (_resolved(cwd, written), imported) == ([page.resolve()], ())


@pytest.mark.parametrize("command", [
    pytest.param("curl -o page.md file:///tmp/page.md", id="file-url"),
    pytest.param("curl -o page.md FILE:///tmp/page.md", id="upper-case-scheme"),
    pytest.param("curl -o page.md https://example.com/page file:///tmp/page.md", id="beside-a-remote-url"),
])
def test_a_file_url_download_into_ignored_scratch_stays_written(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, IGNORED)
    page = _write(cwd / "page.md")

    written, imported = _split(cwd, command)

    assert (_resolved(cwd, written), imported) == ([page.resolve()], ())


def test_a_remote_download_outside_any_git_repo_stays_written(tmp_path: Path) -> None:
    page = _write(tmp_path / "page.md")

    written, imported = _split(tmp_path, "curl -o page.md https://example.com/page")

    assert (_resolved(tmp_path, written), imported) == ([page.resolve()], ())


@pytest.mark.parametrize("command", EXTRACTIONS)
def test_an_extraction_into_ignored_scratch_lands_as_imported(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, IGNORED)
    guide = _archives(cwd)

    assert _split(cwd, command) == ((), (str(guide),))


@pytest.mark.parametrize("command", EXTRACTIONS)
def test_an_extraction_into_a_path_git_does_not_ignore_is_not_imported(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, NOT_IGNORED)
    _archives(cwd)

    _written, imported = _split(cwd, command)

    assert imported == ()


def test_an_extraction_from_an_archive_the_session_wrote_is_not_imported(tmp_path: Path) -> None:
    cwd = _folder(tmp_path, IGNORED)
    _archives(cwd)
    authored = frozenset({temp_copies.source_key(cwd / "bundle.tar")})

    _written, imported = _split(cwd, "tar -xf bundle.tar", authored)

    assert imported == ()


@pytest.mark.parametrize("command", REMOTE_CLONES)
def test_a_remote_clone_into_ignored_scratch_lands_as_imported_without_its_git_directory(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, IGNORED)
    readme = _clone(cwd)

    assert _split(cwd, command) == ((), (str(readme),))


@pytest.mark.parametrize("command", REMOTE_CLONES)
def test_a_remote_clone_into_a_path_git_does_not_ignore_is_not_imported(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, NOT_IGNORED)
    _clone(cwd)

    _written, imported = _split(cwd, command)

    assert imported == ()


@pytest.mark.parametrize("command", [
    pytest.param("git clone /tmp/origin repo", id="absolute-path"),
    pytest.param("git clone ../origin repo", id="relative-path"),
    pytest.param("git clone file:///tmp/origin repo", id="file-url"),
])
def test_a_clone_of_a_local_repository_into_ignored_scratch_is_not_imported(tmp_path: Path, command: str) -> None:
    cwd = _folder(tmp_path, IGNORED)
    _clone(cwd)

    _written, imported = _split(cwd, command)

    assert imported == ()


def test_a_clone_past_the_file_bound_imports_nothing(tmp_path: Path) -> None:
    cwd = _folder(tmp_path, IGNORED)
    _clone(cwd, extra_files=import_landings.MAX_CLONE_FILES)

    assert _split(cwd, "git clone https://example.com/repo.git") == ((), ())


def test_a_plain_redirect_of_echo_into_ignored_scratch_stays_written(tmp_path: Path) -> None:
    cwd = _folder(tmp_path, IGNORED)
    page = _write(cwd / "page.md")

    written, imported = _split(cwd, "echo hi > page.md")

    assert (_resolved(cwd, written), imported) == ([page.resolve()], ())
