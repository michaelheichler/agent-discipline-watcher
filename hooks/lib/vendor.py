"""Copied per host rather than resolved at runtime, because the Cowork VM has no egress and never mounts the home directory."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

try:
    from . import host, host_manifest
except ImportError:
    import host
    import host_manifest


REPO_ROOT = Path(__file__).parents[2]
RUNTIME_PATHS = (
    "hooks", "bin", "scripts", "skills", "hosts", "commands", "install.sh", ".python-version",
)
SKIP_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache"})
_SEPARATORS = re.compile(r"[-_.]")


def owning_host(filename: str) -> str | None:
    """Split on separators because a substring match calls prompt_submit.py an OMP file."""
    named = set(_SEPARATORS.split(filename)) & set(host.SUPPORTED)
    if len(named) > 1:
        raise ValueError(f"{filename} names more than one host: {', '.join(sorted(named))}")
    return next(iter(named), None)


def belongs_to(filename: str, target: str) -> bool:
    """Keep an unnamed file everywhere because the shared core is what makes the runtimes identical."""
    owner = owning_host(filename)
    return owner is None or owner == target


def _wanted(relative: Path, target: str) -> bool:
    parts = relative.parts
    if SKIP_DIRECTORIES & set(parts):
        return False
    return all(belongs_to(part, target) for part in parts)


def _files_under(root: Path, entry: str) -> list[Path]:
    origin = root / entry
    if origin.is_file():
        return [origin]
    if not origin.is_dir():
        return []
    return [path for path in sorted(origin.rglob("*")) if path.is_file()]


def runtime_paths(target: str, root: Path | None = None) -> tuple[str, ...]:
    """Read the extras from the manifest because only OMP owns a whole top-level tree of its own."""
    manifest = host_manifest.load(target, None if root is None else root / "hosts")
    return (*RUNTIME_PATHS, *manifest.extra_paths)


def vendor(target: str, source: str | Path = REPO_ROOT, destination: str | Path = "") -> tuple[Path, ...]:
    """Refuse an unknown host because a guessed roster would ship another host's adapter."""
    if target not in host.SUPPORTED:
        raise ValueError(f"{target} is not a supported host")
    source_root = Path(source)
    destination_root = Path(destination)
    if destination_root.exists():
        shutil.rmtree(destination_root)
    written: list[Path] = []
    for entry in runtime_paths(target, source_root):
        for path in _files_under(source_root, entry):
            relative = path.relative_to(source_root)
            if not _wanted(relative, target):
                continue
            landing = destination_root / relative
            landing.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, landing)
            written.append(relative)
    return tuple(written)


def foreign_files(target: str, tree: str | Path) -> tuple[Path, ...]:
    """Answer with the offenders because a count alone cannot tell a reviewer which host leaked."""
    root = Path(tree)
    return tuple(
        path.relative_to(root) for path in sorted(root.rglob("*"))
        if path.is_file() and not _wanted(path.relative_to(root), target)
    )
