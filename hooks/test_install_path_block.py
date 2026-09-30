"""Sourced helper, because a full install per case is slow."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from install_sandbox import sandbox_env
from lib import nuke_runtime, vendor

COMMON = vendor.REPO_ROOT / "hosts" / "common.sh"
BLOCK = (
    "# >>> agent-discipline-watcher >>>\n"
    'export PATH="$HOME/.adw/bin:$PATH"\n'
    "# <<< agent-discipline-watcher <<<\n"
)
USER_LINES = "alias ll='ls -l'\nexport EDITOR=vim\n"


def _add_block(home: Path, shell: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-c", f'. "{COMMON}"; adw_add_path_block'],
        capture_output=True, text=True, check=True,
        env=sandbox_env(home, PATH="/usr/bin:/bin", SHELL=shell),
    )


@pytest.mark.parametrize(("shell", "rc_name", "other_name"), [
    ("/bin/zsh", ".zshrc", ".bashrc"),
    ("/bin/bash", ".bashrc", ".zshrc"),
])
def test_the_login_shell_rc_gets_the_block_and_the_other_stays_absent(
    tmp_path: Path, shell: str, rc_name: str, other_name: str,
) -> None:
    finished = _add_block(tmp_path, shell)

    assert (tmp_path / rc_name).read_text(encoding="utf-8") == BLOCK
    assert not (tmp_path / other_name).exists()
    assert f"Added ~/.adw/bin to PATH in ~/{rc_name}. Open a new terminal to use adw-config." in finished.stdout


def test_an_unknown_shell_gets_the_printed_line_and_no_rc_file(tmp_path: Path) -> None:
    finished = _add_block(tmp_path, "/usr/bin/fish")

    assert 'export PATH="$HOME/.adw/bin:$PATH"' in finished.stdout
    assert not (tmp_path / ".zshrc").exists()
    assert not (tmp_path / ".bashrc").exists()


def test_a_second_run_leaves_the_rc_file_byte_identical(tmp_path: Path) -> None:
    (tmp_path / ".zshrc").write_text(USER_LINES, encoding="utf-8")
    _add_block(tmp_path, "/bin/zsh")
    first = (tmp_path / ".zshrc").read_bytes()

    second = _add_block(tmp_path, "/bin/zsh")

    assert (tmp_path / ".zshrc").read_bytes() == first
    assert "Added" not in second.stdout


def test_an_old_block_with_other_content_is_replaced_not_duplicated(tmp_path: Path) -> None:
    old_block = (
        "# >>> agent-discipline-watcher >>>\n"
        'export PATH="$HOME/.local/bin:$PATH"\n'
        "# <<< agent-discipline-watcher <<<\n"
    )
    (tmp_path / ".zshrc").write_text(USER_LINES + old_block, encoding="utf-8")

    _add_block(tmp_path, "/bin/zsh")

    assert (tmp_path / ".zshrc").read_text(encoding="utf-8") == USER_LINES + BLOCK


def test_a_user_file_without_a_final_newline_keeps_its_last_line(tmp_path: Path) -> None:
    (tmp_path / ".bashrc").write_text("export EDITOR=vim", encoding="utf-8")

    _add_block(tmp_path, "/bin/bash")

    assert (tmp_path / ".bashrc").read_text(encoding="utf-8") == "export EDITOR=vim\n" + BLOCK


def test_install_then_nuke_leaves_only_the_user_lines(tmp_path: Path) -> None:
    (tmp_path / ".zshrc").write_text(USER_LINES, encoding="utf-8")
    _add_block(tmp_path, "/bin/zsh")

    stripped = nuke_runtime.strip_rc_block((tmp_path / ".zshrc").read_text(encoding="utf-8"))

    assert stripped == USER_LINES
