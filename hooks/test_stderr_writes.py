"""Because a descriptor redirect opens its file whatever the command prints, a stderr route must face the same scan and journal as a stdout route."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import protected
from test_bash_variable_redirects import PROSE, after_run
from test_tests_policy_gate import blocked_by, project, shell

DASH = chr(8212)


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(protected.AUTH_ENV, raising=False)
    monkeypatch.delenv("OMPCODE", raising=False)


@pytest.mark.parametrize("command", [
    pytest.param(f"printf 'x{DASH}y' 2>notes.md >&2", id="R2-5-stdout-joined-to-stderr-file"),
    pytest.param(f"exec 2>notes.md; printf 'x{DASH}y' >&2", id="R2-5-exec-stderr-file"),
])
def test_text_routed_into_a_stderr_file_is_scanned_or_denied(tmp_path: Path, command: str) -> None:
    assert shell(project(tmp_path, tests="deny"), command).get("decision") == "block"


def test_text_written_to_a_file_on_stdout_is_scanned(tmp_path: Path) -> None:
    assert blocked_by(shell(project(tmp_path, tests="deny"), f"printf 'x{DASH}y' >notes.md"), "banned_dash")


@pytest.mark.parametrize("command", [
    pytest.param(f"cat <<'EOF' 2>notes.md\nx{DASH}y\nEOF", id="R2-5-stdout-text-not-in-stderr-file"),
    pytest.param('M=notes.md; printf x 2>"$M"', id="R2-5-variable-stderr-file"),
    pytest.param("printf x > /dev/null", id="R2-5-null-device"),
    pytest.param("printf x >&2", id="R2-5-stderr-stream"),
    pytest.param("printf x > notes.md", id="R2-5-plain-literal"),
])
def test_a_harmless_descriptor_route_passes(tmp_path: Path, command: str) -> None:
    assert shell(project(tmp_path, tests="deny"), command).get("decision") != "block"


@pytest.mark.parametrize("command", [
    pytest.param("printf x 2>notes.md", id="R2-5-literal"),
    pytest.param('M=notes.md; printf x 2>"$M"', id="R2-5-variable"),
    pytest.param("exec 2>notes.md; printf x >&2", id="R2-5-exec"),
    pytest.param("cat <<'EOF' 2>notes.md\nhello\nEOF", id="R2-5-heredoc"),
])
def test_a_file_opened_for_stderr_is_scanned_after_the_run(tmp_path: Path, command: str) -> None:
    cwd = project(tmp_path)
    (cwd / "notes.md").write_text(PROSE, encoding="utf-8")

    response = after_run(cwd, command)

    assert "inflated_diction" in response.get("reason", "")
