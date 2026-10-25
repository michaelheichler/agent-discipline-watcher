"""Because a file URL can fetch the agent's own scratch text, a copy made that way must face the post-run gate like any write."""
from __future__ import annotations

from pathlib import Path

import pytest

import record
from test_tests_policy_gate import isolated
from testing import make_repo

AGENT_CODE = "# Returns the total value\nvalue = 1\n"


def _scratch_copy(tmp_path: Path, destination: str) -> tuple[Path, str]:
    """Copied ahead of the record run, because the gate scans the file the command left behind."""
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    (repo / "scratch").mkdir()
    mine = repo / "scratch" / "mine.py"
    mine.write_text(AGENT_CODE, encoding="utf-8")
    (repo / destination).write_text(AGENT_CODE, encoding="utf-8")
    return repo, f"curl -o {destination} file://{mine}"


@pytest.mark.parametrize("destination", [
    pytest.param("app.py", id="into-the-project"),
    pytest.param("scratch/app.py", id="into-ignored-scratch"),
])
def test_a_file_url_copy_of_the_agents_scratch_file_blocks_on_its_findings(tmp_path: Path, destination: str) -> None:
    repo, command = _scratch_copy(tmp_path, destination)
    payload = {"session_id": "t19", "cwd": str(repo), "tool_name": "Bash", "turn_id": "turn",
               "tool_use_id": "use", "tool_input": {"command": command},
               "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}

    response = record.run(payload, isolated(tmp_path))

    assert (response.get("decision"), destination in response.get("reason", "")) == ("block", True)
