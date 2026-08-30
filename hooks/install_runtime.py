#!/usr/bin/env python3
"""Copy the ADW checkout into its isolated user installation directory."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


INSTALL_MARKER = ".adw-install-marker"
INSTALL_MARKER_CONTENT = "agent-discipline-watcher\n"

EXCLUDED_NAMES = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".venv",
        ".worktrees",
        ".superpowers",
        "__pycache__",
    }
)


def _ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude repository metadata and generated development artifacts."""
    return EXCLUDED_NAMES.intersection(names)


def install(source: Path, destination: Path) -> Path:
    """Replace the managed installation with a copy of the checkout."""
    source = source.expanduser().resolve()
    destination = destination.expanduser()
    if source == destination.resolve():
        raise ValueError("source and installation destination must be different")
    if destination.is_symlink():
        raise RuntimeError(f"refusing to replace symlink installation: {destination}")
    if destination.exists():
        marker = destination / INSTALL_MARKER
        if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding="utf-8") != INSTALL_MARKER_CONTENT:
            raise RuntimeError(f"refusing to replace unowned installation directory: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.install-{os.getpid()}"
    if staging.exists() or staging.is_symlink():
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        else:
            staging.unlink()

    try:
        shutil.copytree(source, staging, ignore=_ignore, symlinks=False)
        (staging / INSTALL_MARKER).write_text(INSTALL_MARKER_CONTENT, encoding="utf-8")
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    except BaseException:
        if staging.exists() or staging.is_symlink():
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            else:
                staging.unlink()
        raise
    return destination


def main() -> None:
    """Parse paths and install the isolated checkout copy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    print(install(args.source, args.destination))


if __name__ == "__main__":
    main()
