from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from install_runtime import INSTALL_MARKER, INSTALL_MARKER_CONTENT, install


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
PI_INSTALL = ROOT / "pi" / "install.sh"


def _stub(directory: Path, name: str, version: str, command: str) -> None:
    path = directory / name
    path.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-c" ]; then printf "%s\\n" "{version}"; exit 0; fi\n'
        + command
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_installer_uses_newest_compatible_python_instead_of_stale_python3() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        binaries = root / "bin"
        binaries.mkdir()
        _stub(binaries, "python3", "3.9.0", "exit 97")
        _stub(binaries, "python3.14", "3.14.0", f'exec "{sys.executable}" "$@"')
        result = subprocess.run(
            [str(INSTALL), "--codex", "-y"],
            env={
                **os.environ,
                "HOME": str(root / "home"),
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            },
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        config = (root / "home" / ".codex" / "config.toml").read_text(encoding="utf-8")
        installed_root = root / "home" / ".adw" / "install" / "agent-discipline-watcher"
        assert str(ROOT) not in config
        assert str(installed_root / "hooks" / "run.sh") in config


def test_omp_installer_uses_newest_compatible_python_instead_of_stale_python3() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        binaries = root / "bin"
        binaries.mkdir()
        _stub(binaries, "python3", "3.9.0", "exit 97")
        _stub(binaries, "python3.14", "3.14.0", f'exec "{sys.executable}" "$@"')
        result = subprocess.run(
            [str(PI_INSTALL), "-y"],
            env={
                **os.environ,
                "HOME": str(root / "home"),
                "PI_CODING_AGENT_DIR": str(root / "agent"),
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            },
            capture_output=True,
            text=True,
            check=False,
        )

    assert result.returncode == 0, result.stderr


def test_omp_custom_install_root_is_runtime_target(tmp_path: Path) -> None:
    """Custom installation roots flow through stable OMP links and settings."""
    home = tmp_path / "home"
    agent_dir = tmp_path / "omp-agent"
    install_dir = tmp_path / "isolated-adw"
    environment = {
        **os.environ,
        "HOME": str(home),
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "ADW_INSTALL_DIR": str(install_dir),
    }

    result = subprocess.run(
        [str(PI_INSTALL), "-y"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (home / ".agents" / "skills" / "agent-discipline-watcher").resolve() == install_dir.resolve()
    assert (agent_dir / "extensions" / "agent-discipline-watcher").resolve() == (
        install_dir / "pi/extensions/agent-discipline-watcher"
    ).resolve()
    settings = (agent_dir / "settings.json").read_text(encoding="utf-8")
    assert str(install_dir) in settings


def test_omp_uninstall_removes_installed_links(tmp_path: Path) -> None:
    """Uninstall removes links that target the isolated installation."""
    home = tmp_path / "home"
    agent_dir = tmp_path / "omp-agent"
    environment = {**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent_dir)}
    installed = subprocess.run(
        [str(PI_INSTALL), "-y"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    install_dir = home / ".adw" / "install" / "agent-discipline-watcher"
    assert (home / ".agents" / "skills" / "agent-discipline-watcher").is_symlink()
    assert (agent_dir / "extensions" / "agent-discipline-watcher").is_symlink()

    removed = subprocess.run(
        [str(PI_INSTALL), "--remove", "-y"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert removed.returncode == 0, removed.stderr
    assert not (home / ".agents" / "skills" / "agent-discipline-watcher").exists()
    assert not (agent_dir / "extensions" / "agent-discipline-watcher").exists()
    assert install_dir.is_dir()


def test_install_copies_code_without_checkout_metadata(tmp_path: Path) -> None:
    """Installed code remains usable after the checkout moves."""
    checkout = tmp_path / "checkout"
    (checkout / "hooks").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "hooks" / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    destination = tmp_path / ".adw" / "install" / "agent-discipline-watcher"

    install(checkout, destination)
    moved_checkout = tmp_path / "moved-checkout"
    checkout.rename(moved_checkout)

    assert (destination / "hooks" / "run.sh").is_file()
    assert not (destination / ".git").exists()
    assert (destination / INSTALL_MARKER).read_text(encoding="utf-8") == INSTALL_MARKER_CONTENT


def test_install_refuses_foreign_install_symlink(tmp_path: Path) -> None:
    """A symlinked destination cannot bypass install ownership checks."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    destination = tmp_path / ".adw" / "install" / "agent-discipline-watcher"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(foreign, target_is_directory=True)

    with pytest.raises(RuntimeError, match="refusing to replace symlink installation"):
        install(checkout, destination)


def test_install_refuses_unowned_destination(tmp_path: Path) -> None:
    """A foreign directory cannot be replaced by the installer."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    destination = tmp_path / ".adw" / "install" / "agent-discipline-watcher"
    destination.mkdir(parents=True)
    (destination / "user-file").write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unowned installation directory"):
        install(checkout, destination)

    assert (destination / "user-file").read_text(encoding="utf-8") == "keep"

def test_combined_install_removes_obsolete_command_links(tmp_path: Path) -> None:
    """Installation removes command links from the retired ADW CLI layout."""
    home = tmp_path / "home"
    obsolete = home / ".local" / "bin" / "agent-discipline"
    obsolete.parent.mkdir(parents=True)
    obsolete.symlink_to(home / "Development/skill-repos/agent-discipline-watcher/bin/agent-discipline")

    result = subprocess.run(
        [str(INSTALL), "--omp"],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not obsolete.exists()
