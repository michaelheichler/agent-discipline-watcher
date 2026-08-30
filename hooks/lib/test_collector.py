from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import collector


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_an_absent_root_yields_defaults_and_raises_nothing(tmp_path: Path) -> None:
    """Answer without a tree because Cowork ships no writable configuration directory."""
    loaded = collector.load((tmp_path / "missing", tmp_path / "gone" / "deeper"))

    assert loaded.values == {}
    assert loaded.sources == ()


def test_an_earlier_root_wins_over_a_later_one(tmp_path: Path) -> None:
    """Order the roots because a project must override whatever a machine set."""
    near = _write(tmp_path / "near" / "config.json", {"max_rows": 3})
    _write(tmp_path / "far" / "config.json", {"max_rows": 9, "baseline": "none"})

    loaded = collector.load((near.parent, tmp_path / "far"))

    assert loaded.values["max_rows"] == 3
    assert loaded.values["baseline"] == "none"


def test_a_partial_tree_loads_what_it_finds(tmp_path: Path) -> None:
    """Tolerate a half-installed tree because an interrupted install must not brick the gate."""
    _write(tmp_path / "second" / "config.json", {"baseline": "git"})

    loaded = collector.load((tmp_path / "first", tmp_path / "second", tmp_path / "third"))

    assert loaded.values == {"baseline": "git"}
    assert loaded.sources == (tmp_path / "second" / "config.json",)


def test_an_unknown_key_is_refused_rather_than_carried(tmp_path: Path) -> None:
    """Reject the key because a value nobody validates would reach a terminal unchecked."""
    _write(tmp_path / "root" / "config.json", {"max_rows": 3, "wat": 1})

    with pytest.raises(collector.CollectorError) as failure:
        collector.load((tmp_path / "root",))

    assert "wat" in str(failure.value)


def test_unreadable_json_names_its_file_and_refuses(tmp_path: Path) -> None:
    """Fail loudly because a silently skipped file would run the wrong policy."""
    target = tmp_path / "root" / "config.json"
    target.parent.mkdir(parents=True)
    target.write_text("{ not json", encoding="utf-8")

    with pytest.raises(collector.CollectorError) as failure:
        collector.load((tmp_path / "root",))

    assert "config.json" in str(failure.value)


def test_a_root_that_is_a_file_is_ignored(tmp_path: Path) -> None:
    """Skip a non-directory because a stale path must not raise on every hook call."""
    decoy = tmp_path / "decoy"
    decoy.write_text("", encoding="utf-8")

    assert collector.load((decoy,)).values == {}


def test_models_load_from_their_own_file(tmp_path: Path) -> None:
    """Keep models apart because a model list changes on a different cadence than policy."""
    _write(tmp_path / "root" / "models.json", {"judge": "claude-haiku-4-5"})

    loaded = collector.load((tmp_path / "root",))

    assert loaded.models == {"judge": "claude-haiku-4-5"}


def test_any_root_the_caller_names_is_read(tmp_path: Path) -> None:
    """Take roots from the caller because a runtime knows its own paths and the core does not."""
    for name in ("claude", "codex", "omp", "cowork", "anything-else"):
        _write(tmp_path / name / "config.json", {"max_rows": 4})

        loaded = collector.load((tmp_path / name,))

        assert loaded.values == {"max_rows": 4}, name
