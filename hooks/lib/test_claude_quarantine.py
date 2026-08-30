from __future__ import annotations

import os
from pathlib import Path

from lib import claude_quarantine

PREFIX = "settings.json"
SUFFIX = ".adw-corrupt."


def _leaf(index: int) -> str:
    return f"{PREFIX}{SUFFIX}{index:016x}"


def _parent_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY)


def _seed(root: Path, count: int, size: int = 4) -> None:
    for index in range(count):
        leaf = root / _leaf(index)
        leaf.write_text("x" * size, encoding="utf-8")
        os.utime(leaf, ns=(index * 1_000_000_000, index * 1_000_000_000))


def test_only_a_sixteen_digit_hex_leaf_counts_as_ours() -> None:
    """Match the exact token because a foreign backup must survive reclamation."""
    assert claude_quarantine.owned_quarantine_name(_leaf(1), PREFIX, SUFFIX)

    assert not claude_quarantine.owned_quarantine_name("settings.json", PREFIX, SUFFIX)
    assert not claude_quarantine.owned_quarantine_name(f"{PREFIX}{SUFFIX}dead", PREFIX, SUFFIX)
    assert not claude_quarantine.owned_quarantine_name(f"{PREFIX}{SUFFIX}" + "g" * 16, PREFIX, SUFFIX)
    assert not claude_quarantine.owned_quarantine_name(f"{PREFIX}{SUFFIX}" + "0" * 17, PREFIX, SUFFIX)
    assert not claude_quarantine.owned_quarantine_name(f"other{SUFFIX}" + "0" * 16, PREFIX, SUFFIX)


def test_the_count_bound_drops_the_oldest_leaf_first(tmp_path: Path) -> None:
    """Sort by modification time because the newest quarantine holds the useful evidence."""
    _seed(tmp_path, 5)
    fd = _parent_fd(tmp_path)
    try:
        claude_quarantine.reclaim_quarantines(fd, PREFIX, SUFFIX, 2, 1_000_000)
    finally:
        os.close(fd)

    survivors = sorted(entry.name for entry in tmp_path.iterdir())
    assert survivors == [_leaf(3), _leaf(4)]


def test_the_byte_bound_drops_beyond_the_count_bound(tmp_path: Path) -> None:
    """Hold both bounds because a few large files exhaust the budget on their own."""
    _seed(tmp_path, 4, size=100)
    fd = _parent_fd(tmp_path)
    try:
        claude_quarantine.reclaim_quarantines(fd, PREFIX, SUFFIX, 10, 150)
    finally:
        os.close(fd)

    survivors = sorted(entry.name for entry in tmp_path.iterdir())
    assert survivors == [_leaf(3)]


def test_a_foreign_neighbour_survives_reclamation(tmp_path: Path) -> None:
    """Leave unmatched names alone because ADW owns only its own token shape."""
    _seed(tmp_path, 3)
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "settings.json.bak").write_text("{}", encoding="utf-8")

    fd = _parent_fd(tmp_path)
    try:
        claude_quarantine.reclaim_quarantines(fd, PREFIX, SUFFIX, 0, 0)
    finally:
        os.close(fd)

    survivors = sorted(entry.name for entry in tmp_path.iterdir())
    assert survivors == ["settings.json", "settings.json.bak"]


def test_a_bound_that_already_holds_removes_nothing(tmp_path: Path) -> None:
    """Stop before the first unlink because reclamation must not churn a healthy tree."""
    _seed(tmp_path, 3)
    fd = _parent_fd(tmp_path)
    try:
        claude_quarantine.reclaim_quarantines(fd, PREFIX, SUFFIX, 5, 1_000_000)
    finally:
        os.close(fd)

    assert len(list(tmp_path.iterdir())) == 3


def test_a_quarantined_directory_leaf_is_removed(tmp_path: Path) -> None:
    """Handle the directory shape because an interrupted write can leave one behind."""
    (tmp_path / _leaf(0)).mkdir()
    fd = _parent_fd(tmp_path)
    try:
        claude_quarantine.reclaim_quarantines(fd, PREFIX, SUFFIX, 0, 0)
    finally:
        os.close(fd)

    assert list(tmp_path.iterdir()) == []


def test_an_unremovable_leaf_does_not_stall_the_sweep(tmp_path: Path, monkeypatch) -> None:
    """Skip a failing unlink because one locked leaf must not block the rest."""
    _seed(tmp_path, 3)
    real_unlink = os.unlink

    def refuse_the_oldest(name, *args, **kwargs) -> None:
        if name == _leaf(0):
            raise OSError(1, "denied")
        return real_unlink(name, *args, **kwargs)

    monkeypatch.setattr(claude_quarantine.os, "unlink", refuse_the_oldest)

    fd = _parent_fd(tmp_path)
    try:
        claude_quarantine.reclaim_quarantines(fd, PREFIX, SUFFIX, 1, 1_000_000)
    finally:
        os.close(fd)

    survivors = sorted(entry.name for entry in tmp_path.iterdir())
    assert survivors == [_leaf(0)]
