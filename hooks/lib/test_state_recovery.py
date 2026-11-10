"""Because readers share state files, replacement must preserve complete data and cleanup failures."""

from collections.abc import Iterator
import json
import os
from pathlib import Path
import stat

import pytest

from lib import state_recovery


@pytest.mark.parametrize(
    "payload, expected",
    [("Grüße\nsecond line\n", b"Gr\xc3\xbc\xc3\x9fe\nsecond line\n"),
     (b"\x00\xff\r\nbytes", b"\x00\xff\r\nbytes")],
)
def test_atomic_write_preserves_exact_text_and_bytes(tmp_path: Path, payload, expected: bytes) -> None:
    target = tmp_path / "state"

    state_recovery.atomic_write(target, payload)

    assert target.read_bytes() == expected
    assert set(tmp_path.iterdir()) == {target}


def test_atomic_json_preserves_nested_values_and_unicode(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    payload = {"name": "Grüße", "items": [None, True, 3, {"value": "line\nnext"}]}

    state_recovery.atomic_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize("scenario", [(False, "text\n", b"text\n"), (True, b"\xff\x00", b"\xff\x00")])
def test_atomic_open_stages_beside_the_unchanged_target_until_commit(
    tmp_path: Path, scenario: tuple,
) -> None:
    binary, payload, expected = scenario
    target = tmp_path / "state"
    target.write_bytes(b"old")

    with state_recovery.atomic_open(target, binary=binary) as stream:
        stream.write(payload)
        stream.flush()
        temporary, = set(tmp_path.iterdir()) - {target}
        assert temporary.read_bytes() == expected
        assert target.read_bytes() == b"old"

    assert target.read_bytes() == expected
    assert set(tmp_path.iterdir()) == {target}


def test_atomic_path_commits_only_after_the_staged_path_is_ready(tmp_path: Path) -> None:
    target = tmp_path / "state"
    target.write_text("old", encoding="utf-8")

    with state_recovery.atomic_path(target) as temporary:
        assert temporary.parent == target.parent
        temporary.write_bytes(b"complete\x00payload")
        assert target.read_text(encoding="utf-8") == "old"

    assert target.read_bytes() == b"complete\x00payload"
    assert set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize(
    "scenario", [(False, "temporary text", b"temporary text"), (True, b"\xff\x00", b"\xff\x00")],
)
def test_temporary_file_uses_the_requested_directory_and_cleans_up(
    tmp_path: Path, scenario: tuple,
) -> None:
    binary, payload, expected = scenario
    with state_recovery.temporary_file(tmp_path, binary=binary) as (temporary, stream):
        stream.write(payload)
        stream.flush()
        assert temporary.parent == tmp_path
        assert temporary.read_bytes() == expected

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param("open", id="atomic-open"),
        pytest.param("path", id="atomic-path"),
    ],
)
def test_interrupted_staging_preserves_the_old_target_and_removes_temporary_files(
    tmp_path: Path, operation: str,
) -> None:
    target = tmp_path / "state"
    target.write_text("old complete value", encoding="utf-8")
    factories = {"open": state_recovery.atomic_open, "path": state_recovery.atomic_path}
    writers = {"open": lambda stream: stream.write("partial"),
               "path": lambda path: path.write_text("partial", encoding="utf-8")}

    with pytest.raises(RuntimeError):
        with factories[operation](target) as staged:
            writers[operation](staged)
            raise RuntimeError("interrupted writer")

    assert target.read_text(encoding="utf-8") == "old complete value"
    assert set(tmp_path.iterdir()) == {target}


def test_temporary_file_cleans_up_when_its_writer_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with state_recovery.temporary_file(tmp_path) as (_temporary, stream):
            stream.write("partial")
            raise RuntimeError("interrupted writer")

    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def restrictive_umask() -> Iterator[None]:
    previous = os.umask(0o027)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.mark.usefixtures("restrictive_umask")
@pytest.mark.parametrize("mode, expected", [(None, 0o640), (0o604, 0o604)])
def test_atomic_write_respects_explicit_permissions_or_the_callers_umask(
    tmp_path: Path, mode: int | None, expected: int,
) -> None:
    target = tmp_path / "state"

    state_recovery.atomic_write(target, "complete", mode=mode)

    assert stat.S_IMODE(target.stat().st_mode) == expected


@pytest.mark.parametrize(
    "scenario",
    [(False, False, []), (True, False, [False]), (False, True, [True]),
     (True, True, [False, True])],
)
def test_atomic_write_syncs_only_the_requested_file_or_parent(
    tmp_path: Path, monkeypatch, scenario: tuple,
) -> None:
    sync, sync_parent, expected = scenario
    synced = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(stat.S_ISDIR(os.fstat(fd).st_mode)))

    state_recovery.atomic_write(tmp_path / "state", "complete", sync=sync, sync_parent=sync_parent)

    assert synced == expected


@pytest.fixture
def directory_descriptor(tmp_path: Path) -> Iterator[int]:
    descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@pytest.mark.usefixtures("restrictive_umask")
@pytest.mark.parametrize("scenario", [(None, 0o640), (0o604, 0o604)])
def test_descriptor_relative_atomic_open_preserves_requested_permissions(
    tmp_path: Path, directory_descriptor: int, scenario: tuple,
) -> None:
    mode, expected = scenario
    target = tmp_path / "state"

    with state_recovery.atomic_open(target, parent_fd=directory_descriptor, mode=mode) as stream:
        stream.write("complete")

    assert stat.S_IMODE(target.stat().st_mode) == expected


def test_secure_directory_callback_rejects_a_changed_leaf_without_replacing_it(
    tmp_path: Path, directory_descriptor: int,
) -> None:
    target = tmp_path / "state"
    target.write_text("old", encoding="utf-8")
    replacement = tmp_path / "replacement"
    replacement.write_text("external change", encoding="utf-8")
    original = target.stat()
    descriptor = directory_descriptor
    checked = []

    def verify() -> None:
        current = os.stat(target.name, dir_fd=descriptor, follow_symlinks=False)
        checked.append(current.st_ino)
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise PermissionError("leaf changed")

    with pytest.raises(PermissionError):
        with state_recovery.atomic_open(target, parent_fd=descriptor, before_replace=verify) as stream:
            stream.write("pending replacement")
            replacement.replace(target)

    assert checked == [target.stat().st_ino]
    assert target.read_text(encoding="utf-8") == "external change"
    assert set(tmp_path.iterdir()) == {target}
