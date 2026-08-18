from __future__ import annotations

import pytest

from lib import blocker_state


def test_pending_and_touched_state_is_scoped_by_agent(tmp_path) -> None:
    blocker_state.set_pending("s1", "a1", "x.py", "fix x", tmp_path)
    blocker_state.touch_paths("s1", "a1", ["x.py"], tmp_path)
    blocker_state.set_pending("s1", "", "parent.py", "fix parent", tmp_path)
    assert blocker_state.snapshot("s1", "a1", tmp_path) == (["fix x"], ["x.py"])
    assert blocker_state.snapshot("s1", "", tmp_path) == (["fix parent"], [])


def test_clearing_one_pending_path_preserves_other_paths(tmp_path) -> None:
    blocker_state.set_pending("s1", "", "a.py", "fix a", tmp_path)
    blocker_state.set_pending("s1", "", "b.py", "fix b", tmp_path)
    blocker_state.clear_pending("s1", "", "a.py", tmp_path)
    assert blocker_state.snapshot("s1", "", tmp_path)[0] == ["fix b"]


def test_reconcile_preserves_concurrent_changes(tmp_path) -> None:
    blocker_state.set_pending("s1", "", "a.py", "old", tmp_path)
    blocker_state.touch_paths("s1", "", ["a.py", "b.py"], tmp_path)
    pending, paths, revision = blocker_state.details("s1", "", tmp_path)
    blocker_state.set_pending("s1", "", "a.py", "new", tmp_path)
    blocker_state.touch_paths("s1", "", ["c.py"], tmp_path)
    blocker_state.reconcile("s1", "", revision, list(pending), paths, tmp_path)
    current, touched, _revision = blocker_state.details("s1", "", tmp_path)
    assert (current, touched) == (
        {"a.py": "new"},
        ["a.py", "b.py", "c.py"],
    )


def test_empty_session_id_raises_instead_of_silently_dropping_the_write(tmp_path) -> None:
    with pytest.raises(ValueError):
        blocker_state.set_pending("", "", "a.py", "fix a", tmp_path)
