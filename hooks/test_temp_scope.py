from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import pre_bash
import pre_write
import record
from lib import journal, protected

DEFERRED = "# " + "TO" + "DO" + " later\nvalue = 1\n"
DASHED = "The scan ran — then it stopped.\n"


def _config(tmp_path: Path) -> dict:
    return {
        "ledger_root": str(tmp_path / "ledger"), "state_root": str(tmp_path / "state"),
        "rule_gates": {"deferred_work_comment": "enforce"},
    }


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    return project


def _write(tmp_path: Path, target: Path, content: str) -> dict:
    payload = {
        "cwd": str(_project(tmp_path)), "session_id": "s1", "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": content},
    }
    return pre_write.run(payload, _config(tmp_path))


def _bash_record(tmp_path: Path, project: Path, command: str) -> dict:
    payload = {
        "cwd": str(project), "session_id": "s1", "tool_name": "Bash",
        "tool_use_id": "t1", "tool_input": {"command": command},
    }
    return record.run(payload, _config(tmp_path))


@pytest.mark.parametrize(("name", "content"), [("dump.py", DEFERRED), ("dump.md", DASHED)])
def test_a_temp_write_outside_the_project_gets_no_findings(tmp_path: Path, name: str, content: str) -> None:
    assert _write(tmp_path, tmp_path / name, content) == {}


@pytest.mark.parametrize("root", ["/tmp", "/private/tmp"])
def test_a_write_under_a_shared_temp_root_gets_no_findings(tmp_path: Path, root: str) -> None:
    assert _write(tmp_path, Path(root) / "adw-khorikov.md", DASHED) == {}


def test_the_same_write_inside_a_temp_project_is_scanned(tmp_path: Path) -> None:
    response = _write(tmp_path, tmp_path / "project" / "dump.py", DEFERRED)

    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]


def test_a_temp_config_that_grants_an_escape_is_still_sealed(tmp_path: Path) -> None:
    grant = json.dumps({protected.AUTH_KEY: True})

    response = _write(tmp_path, tmp_path / protected.CONFIG_SEAL_BASENAME, grant)

    assert response["decision"] == "block"
    assert "config_seal" in response["reason"]


def test_a_shell_redirect_into_temp_gets_no_findings(tmp_path: Path) -> None:
    command = f"printf '%s' '{DASHED.strip()}' > {tmp_path / 'dump.md'}"
    payload = {"cwd": str(_project(tmp_path)), "tool_name": "Bash", "tool_input": {"command": command}}

    assert pre_bash.run(payload, _config(tmp_path)) == {}


def test_a_temp_edit_writes_no_candidate_row(tmp_path: Path) -> None:
    scratch = tmp_path / "notes.md"
    scratch.write_text(DASHED, encoding="utf-8")
    payload = {
        "cwd": str(_project(tmp_path)), "session_id": "s1", "tool_name": "Write",
        "tool_use_id": "t1", "tool_input": {"file_path": str(scratch)},
    }

    assert record.run(payload, _config(tmp_path)) == {}
    assert not journal.read("s1", state_root=str(tmp_path / "state"))


@pytest.mark.parametrize("verb", ["cp", "mv", "install -m 644", "rsync -a"])
def test_a_copy_from_temp_into_the_project_scans_the_destination(tmp_path: Path, verb: str) -> None:
    project = _project(tmp_path)
    source = tmp_path / "dump.py"
    source.write_text(DEFERRED, encoding="utf-8")
    shutil.copy(source, project / "docs" / "dump.py")

    response = _bash_record(tmp_path, project, f"{verb} {source} docs/dump.py")

    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]


def test_a_redirect_from_temp_into_the_project_scans_the_destination(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = tmp_path / "dump.py"
    source.write_text(DEFERRED, encoding="utf-8")
    shutil.copy(source, project / "docs" / "dump.py")

    response = _bash_record(tmp_path, project, f"cat {source} > docs/dump.py")

    assert response["decision"] == "block"
    assert "deferred_work_comment" in response["reason"]


def test_a_copy_from_temp_into_a_project_directory_scans_the_landed_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = tmp_path / "dump.py"
    source.write_text(DEFERRED, encoding="utf-8")
    shutil.copy(source, project / "docs" / "dump.py")

    response = _bash_record(tmp_path, project, f"cp {source} docs/")

    assert response["decision"] == "block"
    assert str(project / "docs" / "dump.py") in response["reason"]
