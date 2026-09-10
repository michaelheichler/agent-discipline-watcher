from __future__ import annotations

import os
import sys
import sysconfig
from importlib.machinery import PathFinder
from pathlib import Path

STDLIB_NAMES = frozenset(sys.stdlib_module_names) | {"sitecustomize", "usercustomize"}


def _search_roots(cwd: str | None) -> tuple[Path, ...]:
    directory = Path(cwd or os.getcwd()).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Python execution directory is not a directory")
    roots = {directory}
    for raw in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        path = Path(raw) if raw else directory
        roots.add((path if path.is_absolute() else directory / path).resolve())
    return tuple(roots)


def _trusted_roots() -> frozenset[Path]:
    return frozenset(Path(sysconfig.get_path(name)).resolve() for name in ("stdlib", "platstdlib"))


def imports_are_trusted(cwd: str | None = None) -> bool:
    if os.environ.get("PYTHONHOME"):
        return False
    try:
        trusted = _trusted_roots()
        PathFinder.invalidate_caches()
        for root in _search_roots(cwd):
            if root in trusted:
                continue
            for module in STDLIB_NAMES:
                spec = PathFinder.find_spec(module, [str(root)])
                if spec is not None and spec.loader is not None:
                    return False
        return True
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False
