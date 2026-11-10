from collections import Counter
import os
from pathlib import Path

import pytest

from lib import secure_fs


@pytest.fixture(name="descriptors")
def tracked_descriptors(monkeypatch) -> tuple[Counter, Counter]:
    opened = Counter()
    closed = Counter()
    open_file, close_file = os.open, os.close

    def observed_open(*args, **kwargs) -> int:
        descriptor = open_file(*args, **kwargs)
        opened[descriptor] += 1
        return descriptor

    def observed_close(descriptor) -> None:
        close_file(descriptor)
        closed[descriptor] += 1

    monkeypatch.setattr(os, "open", observed_open)
    monkeypatch.setattr(os, "close", observed_close)
    return opened, closed


def test_symlink_parent_rejection_closes_every_opened_directory(tmp_path, descriptors) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "source").write_bytes(b"original")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(OSError):
        secure_fs.open_parent(alias / "source")

    assert descriptors[0] == descriptors[1]


@pytest.mark.parametrize("kind", [pytest.param("directory", id="directory"), pytest.param("fifo", id="fifo"), pytest.param("symlink", id="leaf-symlink")])
def test_nonregular_leaves_never_redirect_or_block_a_verified_read(tmp_path, descriptors, kind) -> None:
    source = tmp_path / "leaf"
    nonregular_leaf(source, kind)
    parent = secure_fs.open_parent(source)
    try:
        result = secure_fs.read_regular(parent, source.name, 8)
    finally:
        os.close(parent)

    assert result is None
    assert descriptors[0] == descriptors[1]


def nonregular_leaf(source: Path, kind: str) -> None:
    if kind == "directory":
        source.mkdir()
    elif kind == "fifo":
        os.mkfifo(source)
    else:
        target = source.with_name("outside")
        target.write_bytes(b"secret")
        source.symlink_to(target)


@pytest.mark.parametrize("race", [pytest.param("replace", id="same-size-inode-swap"), pytest.param("grow", id="growth-past-limit")])
def test_verified_reads_reject_concurrent_file_changes_without_leaking(tmp_path, monkeypatch, descriptors, race) -> None:
    source = tmp_path / "leaf"
    source.write_bytes(b"original")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replaced")
    parent = secure_fs.open_parent(source)
    arrange_file_race(monkeypatch, source, replacement, race)

    try:
        with pytest.raises(ValueError):
            secure_fs.read_regular(parent, source.name, 8)
    finally:
        os.close(parent)

    assert descriptors[0] == descriptors[1]


def arrange_file_race(monkeypatch, source: Path, replacement: Path, race: str) -> None:
    open_file, read_file = os.open, os.read
    changed = False

    def swapped_open(path, *args, **kwargs) -> int:
        if path == source.name and "dir_fd" in kwargs:
            replacement.replace(source)
        return open_file(path, *args, **kwargs)

    def growing_read(*args) -> bytes:
        nonlocal changed
        data = read_file(*args)
        if not changed:
            changed = True
            with source.open("ab") as stream:
                stream.write(b"extra")
        return data

    if race == "replace":
        monkeypatch.setattr(os, "open", swapped_open)
    else:
        monkeypatch.setattr(os, "read", growing_read)


def test_verified_read_accepts_stable_content_at_the_limit(tmp_path, descriptors) -> None:
    source = tmp_path / "leaf"
    source.write_bytes(b"original")
    parent = secure_fs.open_parent(source)
    try:
        result = secure_fs.read_regular(parent, source.name, 8)
    finally:
        os.close(parent)

    assert result == b"original"
    assert descriptors[0] == descriptors[1]
