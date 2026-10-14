from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import batch
import record
import stop
from lib import blocker_state, journal, payloads, temp_copies

DASHED = "The scan ran " + chr(0x2014) + " then it stopped.\n"
SECOND_DASH = "A new line " + chr(0x2014) + " written by the agent.\n"
IMPORTED_LEAD = "imported content, not yours"


def _config(tmp_path: Path) -> dict:
    return {"ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state")}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "skills").mkdir(parents=True, exist_ok=True)
    return project


def _run(tmp_path: Path, tool: str, tool_input: dict, call: str = "t1") -> dict:
    payload = {
        "cwd": str(_project(tmp_path)), "session_id": "s1", "tool_name": tool,
        "tool_use_id": call, "tool_input": tool_input,
    }
    return record.run(payload, _config(tmp_path))


def _bash(tmp_path: Path, command: str, call: str = "t1") -> dict:
    return _run(tmp_path, "Bash", {"command": command}, call)


def _copy(tmp_path: Path, source: Path, call: str = "t1") -> dict:
    shutil.copytree(source, _project(tmp_path) / "skills" / source.name, dirs_exist_ok=True)
    return _bash(tmp_path, f"cp -R {source} skills/", call)


def _download(tmp_path: Path, files: dict[str, str]) -> Path:
    source = tmp_path / "download" / "skill"
    for name, body in files.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text(body, encoding="utf-8")
    return source


def _stop(tmp_path: Path, retry: bool = False) -> dict:
    payload = {"session_id": "s1", "cwd": str(_project(tmp_path)), "hook_event_name": "Stop", "stop_hook_active": retry}
    return stop.run(payload, _config(tmp_path))


def _scope(tmp_path: Path) -> tuple[dict[str, str], list[str], int]:
    return blocker_state.details("s1", "", _config(tmp_path)["state_root"])


def test_cp_from_unauthored_temp_gives_advice_not_block(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})

    response = _copy(tmp_path, source)

    assert response.get("decision") != "block"
    assert IMPORTED_LEAD in json.dumps(response)
    assert _scope(tmp_path)[:2] == ({}, [])


def test_cp_from_agent_written_temp_still_blocks(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})
    _run(tmp_path, "Write", {"file_path": str(source / "SKILL.md")}, "t0")

    response = _copy(tmp_path, source)

    assert response["decision"] == "block"
    assert "banned_dash" in response["reason"]


def test_a_redirect_into_temp_in_the_same_command_counts_as_authored(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch.md"
    scratch.write_text(DASHED, encoding="utf-8")
    landed = _project(tmp_path) / "skills" / "notes.md"
    landed.write_text(DASHED, encoding="utf-8")
    payload = {
        "tool_name": "Bash", "cwd": str(_project(tmp_path)),
        "tool_input": {"command": f"printf 'x' > {scratch} && cp {scratch} skills/notes.md"},
    }

    written, imported = payloads.split_edited_paths(payload, frozenset())

    assert str(landed) in written
    assert imported == ()


@pytest.mark.parametrize(("name", "body"), [
    ("long.py", "x = 1\n" * 3000),
    ("font-index.json", json.dumps({"glyphs": ["a" * 64] * 32000})),
])
def test_unchanged_imported_file_never_blocks_stop(tmp_path: Path, name: str, body: str) -> None:
    source = _download(tmp_path, {name: body})
    _copy(tmp_path, source)
    landed = _project(tmp_path) / "skills" / "skill" / name
    blocker_state.touch_paths("s1", "", [str(landed)], _config(tmp_path)["state_root"])

    assert _stop(tmp_path) == {}


def test_edit_of_imported_file_blocks_only_new_findings(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})
    _copy(tmp_path, source)
    landed = _project(tmp_path) / "skills" / "skill" / "SKILL.md"
    landed.write_text(DASHED + SECOND_DASH, encoding="utf-8")

    response = _run(tmp_path, "Edit", {"file_path": str(landed)}, "t2")

    blocked = response["reason"].split("did not write")[0]
    assert response["decision"] == "block"
    assert f"{landed}:2 " in blocked
    assert f"{landed}:1 " not in blocked


def test_landed_files_follow_the_source_not_the_destination(tmp_path: Path) -> None:
    source = _download(tmp_path, {"new.md": "Plain text.\n"})
    destination = _project(tmp_path) / "skills"
    (destination / "old.md").write_text(DASHED, encoding="utf-8")
    (destination / "new.md").write_text("Plain text.\n", encoding="utf-8")
    command = f"cp -R {source}/* skills/"

    landed = temp_copies.temp_copy_destinations(command, _project(tmp_path))

    assert landed == [str(destination / "new.md")]


def test_a_directory_copy_into_an_existing_directory_lands_under_its_name(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": "Plain.\n", "ref/a.md": "Plain.\n"})
    destination = _project(tmp_path) / "skills"
    (destination / "other.md").write_text(DASHED, encoding="utf-8")
    (destination / "skill" / "ref").mkdir(parents=True)
    (destination / "skill" / "SKILL.md").write_text("Plain.\n", encoding="utf-8")
    (destination / "skill" / "ref" / "a.md").write_text("Plain.\n", encoding="utf-8")

    landed = temp_copies.temp_copy_destinations(f"cp -R {source} skills", _project(tmp_path))

    assert sorted(landed) == [str(destination / "skill" / "SKILL.md"), str(destination / "skill" / "ref" / "a.md")]


def test_a_finished_move_lands_only_the_authored_files(tmp_path: Path) -> None:
    destination = _project(tmp_path) / "skills"
    (destination / "old.md").write_text(DASHED, encoding="utf-8")
    (destination / "mine.md").write_text("Plain.\n", encoding="utf-8")
    authored = frozenset({temp_copies.source_key(tmp_path / "gone" / "mine.md")})
    command = f"mv {tmp_path / 'gone'}/*.md skills/"

    owned, imported = temp_copies.copy_landings(command, _project(tmp_path), authored)

    assert (owned, imported) == ([str(destination / "mine.md")], [])


def test_imported_files_write_no_journal_candidate(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})

    _copy(tmp_path, source)

    assert not journal.read("s1", state_root=_config(tmp_path)["state_root"])


def test_imported_advice_is_reported_once(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})
    first = _copy(tmp_path, source, "t1")
    second = _copy(tmp_path, source, "t2")

    assert IMPORTED_LEAD in json.dumps(first)
    assert IMPORTED_LEAD not in json.dumps(second)


def test_many_paths_cost_one_state_update(tmp_path: Path) -> None:
    files = {f"doc{index}.md": DASHED for index in range(20)}
    source = _download(tmp_path, files)
    for name in files:
        _run(tmp_path, "Write", {"file_path": str(source / name)}, f"w-{name}")
    before = _scope(tmp_path)[2]

    response = _copy(tmp_path, source)

    pending, paths, revision = _scope(tmp_path)
    landed = {str(_project(tmp_path) / "skills" / "skill" / name) for name in files}
    assert response["decision"] == "block"
    assert revision == before + 1
    assert landed <= set(paths)
    assert landed <= set(pending)


def test_a_batch_does_not_track_imported_copies(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})

    _batch_copy(tmp_path, source)

    assert _scope(tmp_path)[1] == []


def test_a_batch_still_tracks_a_copy_of_an_agent_written_temp_file(tmp_path: Path) -> None:
    source = _download(tmp_path, {"SKILL.md": DASHED})
    _run(tmp_path, "Write", {"file_path": str(source / "SKILL.md")}, "t0")

    _batch_copy(tmp_path, source)

    assert str(_project(tmp_path) / "skills" / "skill" / "SKILL.md") in _scope(tmp_path)[1]


def _batch_copy(tmp_path: Path, source: Path) -> dict:
    shutil.copytree(source, _project(tmp_path) / "skills" / source.name)
    cwd = str(_project(tmp_path))
    call = {"tool_use_id": "t1", "tool_name": "Bash", "cwd": cwd, "tool_input": {"command": f"cp -R {source} skills/"}}
    return batch.run({"session_id": "s1", "cwd": cwd, "tool_calls": [call]}, _config(tmp_path))
