from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


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
