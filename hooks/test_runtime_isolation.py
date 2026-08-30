from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lib import host, vendor


HOOKS_DIR = Path(__file__).parent
REPO_ROOT = vendor.REPO_ROOT
OWN_TESTS = {
    host.CLAUDE: (
        "lib/test_claude_luna.py",
        "lib/test_claude_native.py",
        "lib/test_claude_quarantine.py",
    ),
    host.CODEX: ("test_task4_codex.py",),
    host.OMP: (),
    host.COWORK: (),
}
SHARED_TESTS = ("lib/test_core_boundary.py", "lib/test_scanner.py", "lib/test_host.py")


def _run_pytest(tree: Path, targets: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider"],
        cwd=tree, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("target", host.SUPPORTED)
def test_a_runtime_passes_its_own_tests_with_the_others_deleted(
    target: str, tmp_path: Path,
) -> None:
    """Run the vendored tree because isolation claimed on paper is not isolation proven on disk."""
    tree = tmp_path / target
    vendor.vendor(target, REPO_ROOT, tree)
    targets = (*SHARED_TESTS, *OWN_TESTS[target])

    finished = _run_pytest(tree / HOOKS_DIR.name, targets)

    assert finished.returncode == 0, finished.stdout[-4000:]


@pytest.mark.parametrize("target", host.SUPPORTED)
def test_a_runtime_carries_no_foreign_adapter(target: str, tmp_path: Path) -> None:
    """Check the tree itself because a passing suite cannot prove another host's file is absent."""
    tree = tmp_path / target
    vendor.vendor(target, REPO_ROOT, tree)

    assert vendor.foreign_files(target, tree) == ()


@pytest.mark.parametrize("target", host.SUPPORTED)
def test_every_vendored_module_compiles(target: str, tmp_path: Path) -> None:
    """Compile the whole tree because a dangling import to a deleted adapter fails only when reached."""
    tree = tmp_path / target
    vendor.vendor(target, REPO_ROOT, tree)

    finished = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(tree)],
        capture_output=True, text=True, check=False,
    )

    assert finished.returncode == 0, finished.stdout + finished.stderr
