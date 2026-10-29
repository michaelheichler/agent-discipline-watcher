"""Skip install.sh here because its venv step costs time on every run."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from lib import vendor

REPO_ROOT = vendor.REPO_ROOT
SANDBOX_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
ROLE_FILE = "hosts/codex/agents/adw-test-writer.toml"
Arrange = Callable[[Path, Path], None]


def _deploy(codex_home: Path, skill_dir: Path) -> subprocess.CompletedProcess[str]:
    """Call the function alone because install.sh also needs a venv."""
    script = (
        f'. "{REPO_ROOT}/hosts/common.sh"; '
        f'. "{REPO_ROOT}/hosts/codex/deploy-agent.sh"; '
        f'adw_deploy_codex_test_writer "{codex_home}" "{skill_dir}"'
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, check=False,
        env={"PATH": SANDBOX_PATH},
    )


def _role_path(codex_home: Path) -> Path:
    return codex_home / "agents" / "adw-test-writer.toml"


def _source_bytes() -> bytes:
    return (REPO_ROOT / ROLE_FILE).read_bytes()


def _snapshot(path: Path) -> tuple[str, bytes]:
    """Read without following because a link and its target both count."""
    return ("link", os.readlink(path).encode()) if path.is_symlink() else ("file", path.read_bytes())


def _nothing(_role: Path, _scratch: Path) -> None:
    return None


def _old_adw_link(role: Path, scratch: Path) -> None:
    """Point into another install root because older installs linked from anywhere."""
    target = scratch / "older-root/agent-discipline-watcher" / ROLE_FILE
    target.parent.mkdir(parents=True)
    target.write_text('name = "adw-test-writer"\ndescription = "stale"\n', encoding="utf-8")
    role.symlink_to(target)


def _stale_adw_copy(role: Path, _scratch: Path) -> None:
    role.write_text('name = "adw-test-writer"\ndescription = "stale"\n', encoding="utf-8")


def _foreign_link(role: Path, scratch: Path) -> None:
    target = scratch / "someone-elses-file.toml"
    target.write_text("not ours", encoding="utf-8")
    role.symlink_to(target)


def _foreign_file(role: Path, _scratch: Path) -> None:
    role.write_text('name = "someone-else"\n', encoding="utf-8")


@pytest.mark.parametrize("arrange", [
    pytest.param(_nothing, id="empty-home"),
    pytest.param(_old_adw_link, id="old-adw-link"),
    pytest.param(_stale_adw_copy, id="stale-adw-copy"),
])
def test_deploy_leaves_a_regular_copy_of_the_role_file(tmp_path: Path, arrange: Arrange) -> None:
    """Copy because Codex opens a role file with O_NOFOLLOW at spawn."""
    codex_home = tmp_path / "codex_home"
    (codex_home / "agents").mkdir(parents=True)
    role = _role_path(codex_home)
    arrange(role, tmp_path)

    finished = _deploy(codex_home, REPO_ROOT)

    assert finished.returncode == 0, finished.stderr
    assert (role.is_symlink(), role.read_bytes()) == (False, _source_bytes())


def test_deploy_twice_leaves_one_regular_copy_of_the_source(tmp_path: Path) -> None:
    """Run it twice because an installer reruns on every upgrade."""
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    role = _role_path(codex_home)

    _deploy(codex_home, REPO_ROOT)
    finished = _deploy(codex_home, REPO_ROOT)

    assert finished.returncode == 0, finished.stderr
    assert list((codex_home / "agents").iterdir()) == [role]
    assert (role.is_symlink(), role.read_bytes()) == (False, _source_bytes())


@pytest.mark.parametrize("arrange", [
    pytest.param(_foreign_link, id="foreign-link"),
    pytest.param(_foreign_file, id="foreign-file"),
])
def test_deploy_refuses_a_role_file_it_does_not_own(tmp_path: Path, arrange: Arrange) -> None:
    """Refuse the clobber because another tool may own that name."""
    codex_home = tmp_path / "codex_home"
    (codex_home / "agents").mkdir(parents=True)
    role = _role_path(codex_home)
    arrange(role, tmp_path)
    before = _snapshot(role)

    finished = _deploy(codex_home, REPO_ROOT)

    assert finished.returncode != 0
    assert list((codex_home / "agents").iterdir()) == [role]
    assert _snapshot(role) == before
