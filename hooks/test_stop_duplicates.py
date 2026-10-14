from __future__ import annotations

from pathlib import Path

import stop
from lib import blocker_state

BODY = "".join(f"value_{index} = {index}\n" for index in range(40))


def _config(root: Path) -> dict[str, str]:
    return {"ledger_root": str(root / "ledger"), "state_root": str(root / "state")}


def _twins(tmp_path: Path) -> None:
    paths = []
    for name in ("a", "b"):
        target = tmp_path / name / "settings.py"
        target.parent.mkdir()
        target.write_text(BODY, encoding="utf-8")
        paths.append(str(target))
    blocker_state.touch_paths("s1", "", paths, _config(tmp_path)["state_root"])


def _stop(tmp_path: Path) -> dict:
    return stop.run({"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "Stop"}, _config(tmp_path))


def test_stop_finds_no_duplicate_the_batch_gate_never_blocked(tmp_path: Path) -> None:
    _twins(tmp_path)

    assert _stop(tmp_path) == {}


def test_stop_keeps_a_duplicate_the_batch_gate_blocked(tmp_path: Path) -> None:
    _twins(tmp_path)
    blocker_state.set_pending("s1", "", "<batch>", "Duplicate content", _config(tmp_path)["state_root"])

    response = _stop(tmp_path)

    assert response["decision"] == "block"
    assert "duplicate_file_content" in response["reason"]


def test_an_edit_that_keeps_the_copies_equal_blocks_again_after_a_release(tmp_path: Path) -> None:
    _twins(tmp_path)
    blocker_state.set_pending("s1", "", "<batch>", "Duplicate content", _config(tmp_path)["state_root"])
    assert "decision" not in [_stop(tmp_path) for _ in range(3)][2]

    for name in ("a", "b"):
        (tmp_path / name / "settings.py").write_text(BODY + "extra = 1\n", encoding="utf-8")

    assert _stop(tmp_path)["decision"] == "block"
