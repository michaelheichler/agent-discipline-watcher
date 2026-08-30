from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lib import host, host_manifest, vendor


REPO_ROOT = vendor.REPO_ROOT
INSTALLER = REPO_ROOT / "install.sh"


def _run(arguments: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALLER), *arguments],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
            "ADW_INSTALL_DIR": str(home / ".adw" / "install" / "adw"),
        },
    )


def _touched(home: Path) -> list[Path]:
    """Ignore the whole Library tree because macOS writes a bytecode cache whenever any Python runs."""
    return [
        path.relative_to(home) for path in sorted(home.rglob("*"))
        if "Library" not in path.relative_to(home).parts
    ]


def test_a_selection_dispatches_only_the_chosen_hosts(tmp_path: Path) -> None:
    """Map the choice to the dispatch because the router decides what lands on disk."""
    finished = _run(["--codex", "--dry-run"], tmp_path)

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip().endswith(f"hosts/{host.CODEX}/install.sh")
    assert host.OMP not in finished.stdout


def test_two_selections_dispatch_both_in_roster_order(tmp_path: Path) -> None:
    """Keep the order because a reader who picked two expects them in the order they saw."""
    finished = _run(["--omp", "--codex", "--dry-run"], tmp_path)
    dispatched = [Path(line).parent.name for line in finished.stdout.split()]

    assert dispatched == [host.OMP, host.CODEX]


def test_the_flag_path_dispatches_without_a_terminal(tmp_path: Path) -> None:
    """Run with stdin closed because an agent or a CI job has no terminal to draw a picker on."""
    finished = _run(["--claude", "--dry-run"], tmp_path)

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip().endswith(f"hosts/{host.CLAUDE}/install.sh")


def test_no_selection_and_no_terminal_writes_nothing(tmp_path: Path) -> None:
    """Refuse rather than guess because installing every host would be the worst default."""
    finished = _run([], tmp_path)

    assert finished.returncode != 0
    assert _touched(tmp_path) == []


def test_a_dry_run_writes_nothing_at_all(tmp_path: Path) -> None:
    """Keep the dry run dry because a reader checking the plan has not agreed to an install."""
    _run(["--codex", "--omp", "--dry-run"], tmp_path)

    assert _touched(tmp_path) == []


def test_an_unknown_flag_is_refused_rather_than_ignored(tmp_path: Path) -> None:
    """Refuse the typo because silently installing nothing looks the same as success."""
    finished = _run(["--kodex", "--dry-run"], tmp_path)

    assert finished.returncode == 2
    assert "unknown option" in finished.stderr


def test_the_list_flag_matches_the_manifests(tmp_path: Path) -> None:
    """Read one roster because a second list in bash would drift from the manifests."""
    finished = _run(["--list"], tmp_path)

    assert finished.stdout.split() == [entry.name for entry in host_manifest.installable()]


@pytest.mark.parametrize("target", (host.CLAUDE, host.CODEX, host.OMP))
def test_every_dispatched_installer_exists_in_the_repo(target: str, tmp_path: Path) -> None:
    """Check the repo copy because the router runs the deployed copy of this same file."""
    finished = _run([f"--{target}", "--dry-run"], tmp_path)
    deployed = Path(finished.stdout.strip())
    source = REPO_ROOT / "hosts" / deployed.parent.name / deployed.name

    assert source.is_file()


def test_claude_writes_only_the_paths_its_manifest_declares(tmp_path: Path) -> None:
    """Install for real because a dry run cannot prove the write surface stays inside the manifest."""
    finished = _run(["--claude"], tmp_path)
    assert finished.returncode == 0, finished.stderr
    written = {str(path) for path in _touched(tmp_path) if not str(path).startswith(".adw/install")}

    assert ".adw/bin/adw-judge" in written
    assert not [path for path in written if path.startswith(".codex")]
    assert not [path for path in written if path.startswith(".agents")]


def test_the_claude_install_keeps_its_launcher_inside_the_state_directory(tmp_path: Path) -> None:
    """Own the launcher because ~/.local/bin belongs to the user and every tool competes for that name."""
    finished = _run(["--claude"], tmp_path)
    assert finished.returncode == 0, finished.stderr
    written = {str(path) for path in _touched(tmp_path)}

    assert not [path for path in written if path.startswith(".local/bin")]


def test_the_claude_install_never_edits_a_shell_startup_file(tmp_path: Path) -> None:
    """Leave the rc alone because a PATH line the user did not write is a change they cannot see."""
    for name in (".zshrc", ".bashrc"):
        (tmp_path / name).write_text("# user content\n", encoding="utf-8")

    finished = _run(["--claude"], tmp_path)
    assert finished.returncode == 0, finished.stderr

    for name in (".zshrc", ".bashrc"):
        assert (tmp_path / name).read_text(encoding="utf-8") == "# user content\n"
