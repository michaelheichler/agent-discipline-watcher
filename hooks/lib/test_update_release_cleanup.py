from __future__ import annotations

from pathlib import Path

import pytest

from lib import update_release
from lib.test_update_release import COMMIT, TAG, _archive


@pytest.fixture
def destination(tmp_path, monkeypatch):
    archive = _archive()
    monkeypatch.setattr(update_release, "_get_bytes", lambda *_args: archive)
    return tmp_path / "stage"


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_failed_creation_does_not_clean_a_racing_destination(destination, tmp_path, monkeypatch, replacement):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "sentinel").write_text("keep", encoding="utf-8")
    mkdir = Path.mkdir

    def swap_before_mkdir(path, *args, **kwargs):
        if path == destination:
            if replacement == "symlink":
                path.symlink_to(foreign, target_is_directory=True)
            else:
                foreign.rename(path)
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", swap_before_mkdir)
    with pytest.raises(FileExistsError):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert (destination / "sentinel").read_text() == "keep"
    assert destination.is_symlink() == (replacement == "symlink")


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_cleanup_rejects_replacements_of_the_created_directory(destination, tmp_path, monkeypatch, replacement):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "sentinel").write_text("keep", encoding="utf-8")
    original = tmp_path / "original-stage"
    state = update_release._destination_state
    calls = 0

    def swap_after_creation(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.rename(original)
            if replacement == "symlink":
                path.symlink_to(foreign, target_is_directory=True)
            else:
                foreign.rename(path)
        return state(path)

    monkeypatch.setattr(update_release, "_destination_state", swap_after_creation)
    with pytest.raises(ValueError):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert (destination / "sentinel").read_text() == "keep"
    assert original.is_dir()


def test_cleanup_preserves_untracked_files_even_in_its_created_directory(destination, monkeypatch):
    def failed_extraction(bundle, archive, target):
        (target / "untracked").write_text("keep", encoding="utf-8")
        raise OSError("extraction failed")

    monkeypatch.setattr(update_release, "_extract", failed_extraction)
    with pytest.raises(OSError, match="extraction failed"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert (destination / "untracked").read_text() == "keep"


def test_failed_extraction_removes_only_its_tracked_files_and_empty_root(destination, monkeypatch):
    extract_file = update_release._extract_file

    def failed_file(*args):
        extract_file(*args)
        raise OSError("extraction failed")

    monkeypatch.setattr(update_release, "_extract_file", failed_file)
    with pytest.raises(OSError, match="extraction failed"):
        update_release.stage_release(update_release.Release(TAG, COMMIT), destination)
    assert not destination.exists()
