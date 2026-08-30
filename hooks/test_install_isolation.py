from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lib import host, vendor


REPO_ROOT = vendor.REPO_ROOT
SANDBOX_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"


def _install(checkout: Path, home: Path, flag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(checkout / "install.sh"), flag],
        cwd=checkout, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        env={
            "HOME": str(home),
            "PATH": SANDBOX_PATH,
            "ADW_INSTALL_DIR": str(home / ".adw" / "install" / "adw"),
        },
    )


def test_a_vendored_runtime_carries_its_own_installer(tmp_path: Path) -> None:
    """Ship the entrypoint because a runtime that cannot install itself is not a runtime."""
    written = vendor.vendor(host.CODEX, REPO_ROOT, tmp_path / "codex")

    assert Path("install.sh") in written


def test_a_claude_install_leaves_no_codex_or_omp_file(tmp_path: Path) -> None:
    """Check the disk because the whole split exists so one host cannot drag in another."""
    home = tmp_path / "home"
    home.mkdir()

    finished = _install(REPO_ROOT, home, "--claude")

    assert finished.returncode == 0, finished.stderr
    assert not (home / ".codex").exists()
    assert not (home / ".omp").exists()
    assert not (home / ".agents").exists()


def test_a_moved_checkout_does_not_break_an_installed_runtime(tmp_path: Path) -> None:
    """Move the source because a rename must not disable a gate the user already installed."""
    checkout = tmp_path / "checkout-before"
    home = tmp_path / "home"
    home.mkdir()
    vendor.vendor(host.CLAUDE, REPO_ROOT, checkout)

    assert _install(checkout, home, "--claude").returncode == 0
    shutil.move(str(checkout), str(tmp_path / "checkout-after"))

    launcher = home / ".adw" / "bin" / "adw-judge"
    assert launcher.is_symlink()
    assert launcher.resolve().is_file(), "the launcher points at the moved checkout"

    finished = subprocess.run(
        [str(launcher), "status"],
        capture_output=True, text=True, check=False,
        env={"HOME": str(home), "PATH": SANDBOX_PATH},
    )

    assert finished.returncode == 0, finished.stderr


def test_the_installed_copy_never_points_back_at_the_checkout(tmp_path: Path) -> None:
    """Resolve every link because one edge back into the checkout is what a move breaks."""
    checkout = tmp_path / "checkout"
    home = tmp_path / "home"
    home.mkdir()
    vendor.vendor(host.CLAUDE, REPO_ROOT, checkout)
    _install(checkout, home, "--claude")

    links = [path for path in (home / ".adw" / "bin").iterdir() if path.is_symlink()]

    assert links
    for link in links:
        assert checkout not in link.resolve().parents, f"{link.name} points into the checkout"


@pytest.mark.parametrize("flag", ("--claude", "--codex", "--omp"))
def test_no_host_installer_writes_outside_its_declared_surface(flag: str, tmp_path: Path) -> None:
    """Run the dispatch dry because a real Codex install builds a virtual environment over the network."""
    home = tmp_path / "home"
    home.mkdir()

    finished = subprocess.run(
        [str(REPO_ROOT / "install.sh"), flag, "--dry-run"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        env={"HOME": str(home), "PATH": SANDBOX_PATH, "ADW_INSTALL_DIR": str(home / ".adw")},
    )

    assert finished.returncode == 0, finished.stderr
    assert [entry for entry in os.listdir(home) if entry != "Library"] == []
