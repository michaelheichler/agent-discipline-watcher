"""Skip install.sh here because its venv step costs time on every run."""
from __future__ import annotations

import subprocess
from pathlib import Path

from lib import vendor

REPO_ROOT = vendor.REPO_ROOT
SANDBOX_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
ROLE_FILE = "hosts/codex/agents/adw-test-writer.toml"


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


def test_deploy_links_the_role_file_into_codex_home(tmp_path: Path) -> None:
    """Link into place because Codex reads its role files from disk."""
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()

    finished = _deploy(codex_home, REPO_ROOT)

    assert finished.returncode == 0, finished.stderr
    link = codex_home / "agents" / "adw-test-writer.toml"
    assert link.is_symlink()
    assert link.resolve() == (REPO_ROOT / ROLE_FILE).resolve()


def test_deploy_twice_stays_linked_at_the_same_target(tmp_path: Path) -> None:
    """Run it twice because an installer reruns on every upgrade."""
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()

    _deploy(codex_home, REPO_ROOT)
    finished = _deploy(codex_home, REPO_ROOT)

    assert finished.returncode == 0, finished.stderr
    link = codex_home / "agents" / "adw-test-writer.toml"
    assert link.resolve() == (REPO_ROOT / ROLE_FILE).resolve()


def test_deploy_refuses_to_replace_a_foreign_link(tmp_path: Path) -> None:
    """Refuse the clobber because another tool may own that name."""
    codex_home = tmp_path / "codex_home"
    (codex_home / "agents").mkdir(parents=True)
    foreign_target = tmp_path / "someone-elses-file.toml"
    foreign_target.write_text("not ours", encoding="utf-8")
    (codex_home / "agents" / "adw-test-writer.toml").symlink_to(foreign_target)

    finished = _deploy(codex_home, REPO_ROOT)

    assert finished.returncode != 0
    link = codex_home / "agents" / "adw-test-writer.toml"
    assert link.resolve() == foreign_target.resolve()
