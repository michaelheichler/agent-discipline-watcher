from __future__ import annotations

import re
from pathlib import Path

import stop
from lib import blocker_state

NARRATION = "# Increment the counter.\nx = 1\n"


def _root(tmp_path: Path) -> str:
    return str(tmp_path / "state")


def _scope(tmp_path: Path) -> blocker_state.BlockerScope:
    return blocker_state.BlockerScope("s1", "", _root(tmp_path))


def _clean(tmp_path: Path, prefix: str, count: int) -> list[str]:
    return [str(tmp_path / f"{prefix}{index}.py") for index in range(count)]


def _stop(tmp_path: Path) -> dict:
    config = {"ledger_root": str(tmp_path / "ledger"), "state_root": _root(tmp_path)}
    return stop.run({"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "Stop"}, config)


def test_a_full_scope_counts_the_clean_paths_it_dropped_once(tmp_path: Path) -> None:
    blocker_state.touch_paths(_scope(tmp_path), _clean(tmp_path, "gone", blocker_state.MAX_SCOPE_PATHS + 5))

    first = _stop(tmp_path)
    second = _stop(tmp_path)

    assert re.search(r"\b5\b", first["systemMessage"])
    assert second == {}


def test_the_cap_evicts_the_oldest_clean_path_and_keeps_an_older_blocked_one(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    blocked = str(tmp_path / "old.py")
    blocker_state.apply_paths(scope, [blocked], {blocked: "Fix old.py"})
    newer = _clean(tmp_path, "n", blocker_state.MAX_SCOPE_PATHS)

    blocker_state.touch_paths(scope, newer)

    pending, paths, _revision = blocker_state.details("s1", "", _root(tmp_path))
    assert blocked in pending
    assert paths == [blocked, *newer[1:]]
    assert blocker_state.take_dropped(scope) == 1


def test_a_scope_where_every_path_holds_a_blocker_evicts_only_the_clean_newcomer(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    blocked = _clean(tmp_path, "b", blocker_state.MAX_SCOPE_PATHS)
    blocker_state.apply_paths(scope, blocked, {path: f"Fix {path}" for path in blocked})

    blocker_state.touch_paths(scope, [str(tmp_path / "newcomer.py")])

    pending, paths, _revision = blocker_state.details("s1", "", _root(tmp_path))
    assert paths == blocked
    assert sorted(pending) == sorted(blocked)


def test_a_blocker_on_a_path_pushed_past_the_cap_still_blocks_stop(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    target = tmp_path / "a.py"
    target.write_text(NARRATION, encoding="utf-8")
    blocker_state.apply_paths(scope, [str(target)], {str(target): "Fix a.py"})
    blocker_state.touch_paths(scope, _clean(tmp_path, "n", blocker_state.MAX_SCOPE_PATHS))

    response = _stop(tmp_path)

    assert response["decision"] == "block"
    assert "a.py:1" in response["reason"]
