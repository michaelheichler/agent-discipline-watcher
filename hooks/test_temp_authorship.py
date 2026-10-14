from __future__ import annotations

import json
import shutil
from pathlib import Path

import record
import stop
from lib import session_state, temp_authorship, temp_copies

DASHED = "The scan ran " + chr(0x2014) + " then it stopped.\n"
IMPORTED_LEAD = "imported content, not yours"


def _config(tmp_path: Path) -> dict:
    return {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return project


def _bash(tmp_path: Path, command: str, call: str) -> dict:
    payload = {
        "cwd": str(_project(tmp_path)), "session_id": "s1", "tool_name": "Bash",
        "tool_use_id": call, "tool_input": {"command": command},
    }
    return record.run(payload, _config(tmp_path))


def _stop(tmp_path: Path) -> dict:
    payload = {"session_id": "s1", "cwd": str(_project(tmp_path)), "hook_event_name": "Stop"}
    return stop.run(payload, _config(tmp_path))


def _scratch_writes(tmp_path: Path, count: int, call: str = "t1") -> dict:
    padding = [tmp_path / f"padding-{index}" for index in range(count)]
    for path in padding:
        path.write_text("x", encoding="utf-8")
    return _bash(tmp_path, "; ".join(f"printf x > {path}" for path in padding), call)


def _copy_in(tmp_path: Path, source: Path) -> dict:
    landed = _project(tmp_path) / "notes.md"
    shutil.copyfile(source, landed)
    return _bash(tmp_path, f"cp {source} {landed}", "t2")


def _dashed(tmp_path: Path, name: str) -> Path:
    source = tmp_path / name
    source.write_text(DASHED, encoding="utf-8")
    return source


def test_an_authored_source_still_blocks_after_256_later_scratch_writes(tmp_path: Path) -> None:
    source = _dashed(tmp_path, "scratch.md")
    _bash(tmp_path, f"printf x > {source}", "t0")
    _scratch_writes(tmp_path, 256)

    response = _copy_in(tmp_path, source)

    assert response["decision"] == "block"
    assert "banned_dash" in response["reason"]
    assert _stop(tmp_path)["decision"] == "block"


def test_an_external_source_stays_imported_after_300_scratch_writes(tmp_path: Path) -> None:
    _scratch_writes(tmp_path, 300)
    source = _dashed(tmp_path, "downloaded.md")

    response = _copy_in(tmp_path, source)

    assert response.get("decision") != "block"
    assert IMPORTED_LEAD in json.dumps(response)
    assert _stop(tmp_path) == {}


def test_past_the_hard_cap_every_temp_copy_blocks_with_one_notice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(temp_authorship, "MAX_LINES", 3)
    first = _scratch_writes(tmp_path, 4, "t0")
    later = _scratch_writes(tmp_path, 5, "t1")
    source = _dashed(tmp_path, "downloaded.md")

    response = _copy_in(tmp_path, source)

    assert temp_authorship.OVERFLOW_NOTICE in json.dumps(first)
    assert temp_authorship.OVERFLOW_NOTICE not in json.dumps(later)
    assert response["decision"] == "block"


def test_a_legacy_state_list_moves_into_the_store_on_read(tmp_path: Path) -> None:
    root = _config(tmp_path)["state_root"]
    source = _dashed(tmp_path, "scratch.md")
    key = temp_copies.source_key(source)
    session_state.update_state("s1", lambda state: {**state, "authored_temp": [key]}, root)

    authored = temp_authorship.authored_temp("s1", root)

    assert authored == frozenset({key})
    assert "authored_temp" not in session_state.read_state("s1", root)
    assert _copy_in(tmp_path, source)["decision"] == "block"


def test_a_path_with_a_newline_stays_one_entry(tmp_path: Path) -> None:
    root = _config(tmp_path)["state_root"]
    odd = str(tmp_path / "a\nb")

    temp_authorship.note_authored_temp("s1", [odd], None, root)

    assert temp_authorship.authored_temp("s1", root) == frozenset({temp_copies.source_key(odd)})
