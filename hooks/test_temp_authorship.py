from __future__ import annotations

import json
import shutil
from pathlib import Path

import pre_bash
import pre_write
import record
import stop
from lib import blocker_state, session_state, temp_authorship, temp_copies

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


def _at_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(temp_authorship, "MAX_LINES", 3)
    _scratch_writes(tmp_path, 4, "t0")


def _pre(tmp_path: Path, hook, tool: str, tool_input: dict) -> dict:
    payload = {
        "cwd": str(_project(tmp_path)), "session_id": "s1", "tool_name": tool,
        "tool_use_id": "p1", "tool_input": tool_input,
    }
    return hook.run(payload, _config(tmp_path))


def test_one_call_past_the_cap_still_records_every_path(tmp_path: Path, monkeypatch) -> None:
    _at_cap(tmp_path, monkeypatch)

    assert len(temp_authorship.authored_temp("s1", _config(tmp_path)["state_root"])) == 4


def test_at_the_cap_a_scratch_write_is_refused(tmp_path: Path, monkeypatch) -> None:
    _at_cap(tmp_path, monkeypatch)

    response = _pre(tmp_path, pre_write, "Write", {"file_path": str(tmp_path / "more.md"), "content": "x\n"})

    assert response["decision"] == "block"
    assert response["reason"] == temp_authorship.FULL_REASON


def test_at_the_cap_a_scratch_redirect_is_refused(tmp_path: Path, monkeypatch) -> None:
    _at_cap(tmp_path, monkeypatch)

    response = _pre(tmp_path, pre_bash, "Bash", {"command": f"printf x > {tmp_path / 'more.txt'}"})

    assert response["decision"] == "block"
    assert response["reason"] == temp_authorship.FULL_REASON


def test_at_the_cap_a_rewrite_of_a_recorded_scratch_path_passes(tmp_path: Path, monkeypatch) -> None:
    _at_cap(tmp_path, monkeypatch)
    recorded = tmp_path / "padding-0"

    write = _pre(tmp_path, pre_write, "Write", {"file_path": str(recorded), "content": "y\n"})
    redirect = _pre(tmp_path, pre_bash, "Bash", {"command": f"printf y > {recorded}"})

    assert write.get("decision") != "block"
    assert redirect.get("decision") != "block"


def test_at_the_cap_a_project_write_still_passes(tmp_path: Path, monkeypatch) -> None:
    _at_cap(tmp_path, monkeypatch)

    response = _pre(tmp_path, pre_write, "Write", {"file_path": str(_project(tmp_path) / "ok.py"), "content": "x = 1\n"})

    assert response.get("decision") != "block"


def test_at_the_cap_an_external_copy_stays_imported(tmp_path: Path, monkeypatch) -> None:
    _at_cap(tmp_path, monkeypatch)

    response = _copy_in(tmp_path, _dashed(tmp_path, "downloaded.md"))

    assert response.get("decision") != "block"
    assert IMPORTED_LEAD in json.dumps(response)
    assert _stop(tmp_path) == {}


def test_past_200001_seeded_paths_an_external_copy_stays_imported(tmp_path: Path) -> None:
    root = _config(tmp_path)["state_root"]
    seeded = [str(tmp_path / f"authored-{index}") for index in range(temp_authorship.MAX_LINES + 1)]
    temp_authorship.note_authored_temp("s1", seeded, str(_project(tmp_path)), root)

    response = _copy_in(tmp_path, _dashed(tmp_path, "third-party.md"))

    assert len(temp_authorship.authored_temp("s1", root)) == temp_authorship.MAX_LINES + 1
    assert response.get("decision") != "block"
    assert IMPORTED_LEAD in json.dumps(response)


def test_a_torn_last_line_cannot_swallow_the_next_entry_and_is_noticed_once(tmp_path: Path) -> None:
    root = _config(tmp_path)["state_root"]
    directory = session_state.session_directory("s1", root)
    directory.mkdir(parents=True)
    (directory / temp_authorship.AUTHORED_FILENAME).write_text('"/tmp/half', encoding="utf-8")
    scratch = str(tmp_path / "next.md")

    temp_authorship.note_authored_temp("s1", [scratch], None, root)

    assert temp_authorship.authored_temp("s1", root) == frozenset({temp_copies.source_key(scratch)})
    assert "1 damaged lines" in temp_authorship.take_malformed_notice("s1", root)
    assert temp_authorship.take_malformed_notice("s1", root) == ""


def test_a_failing_append_holds_the_turn(tmp_path: Path) -> None:
    directory = session_state.session_directory("s1", _config(tmp_path)["state_root"])
    directory.mkdir(parents=True)
    store = directory / temp_authorship.AUTHORED_FILENAME
    store.write_text('"/tmp/earlier"\n', encoding="utf-8")
    store.chmod(0o400)

    response = _scratch_writes(tmp_path, 1)

    assert response["decision"] == "block"
    assert record.UNDECIDABLE_KEY in blocker_state.details("s1", "", _config(tmp_path)["state_root"])[0]


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
