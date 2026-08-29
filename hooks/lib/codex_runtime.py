"""Resolve the persistent ADW-owned Python runtime used by Luna."""
from __future__ import annotations

import os
import sys
from pathlib import Path


OPENAI_CODEX_VERSION = "0.147.0"
OPENAI_CODEX_REQUIREMENT = f"openai-codex=={OPENAI_CODEX_VERSION}"
RUNTIME_DIRNAME = "codex"
VENV_DIRNAME = "venv"


def runtime_root(root: str | os.PathLike[str] | None = None) -> Path:
    """Keep the install runtime under the retention-exempt ADW runtime root."""
    if root is not None:
        return Path(root)
    return Path.home() / ".adw" / "runtime" / RUNTIME_DIRNAME


def runtime_python(root: str | os.PathLike[str] | None = None) -> Path:
    """Return the pinned runtime interpreter, without falling back silently."""
    return runtime_root(root) / VENV_DIRNAME / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def installed(root: str | os.PathLike[str] | None = None) -> bool:
    path = runtime_python(root)
    return path.is_file() and os.access(path, os.X_OK)


def require_runtime(root: str | os.PathLike[str] | None = None) -> Path:
    path = runtime_python(root)
    if not installed(root):
        raise RuntimeError(
            "The ADW Codex runtime is not installed; rerun install.sh --codex to install "
            f"{OPENAI_CODEX_REQUIREMENT}."
        )
    return path


def test_runtime_or_current(root: str | os.PathLike[str] | None = None) -> Path:
    """Use explicit test roots without requiring a network-installed SDK."""
    if root is not None and not installed(root):
        return Path(sys.executable)
    return require_runtime(root)
