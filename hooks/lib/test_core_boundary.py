from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lib import host


LIB_DIR = Path(__file__).parent
HOOKS_DIR = LIB_DIR.parent
HOST_PREFIXES = tuple(f"{name}_" for name in host.SUPPORTED)
DECLARED_SEAM = "turn_adapter"


def _module_paths() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path for path in LIB_DIR.glob("*.py")
            if not path.name.startswith("test_") and path.name != "__init__.py"
        )
    )


def _is_host_module(name: str) -> bool:
    return name.startswith(HOST_PREFIXES)


def _host_modules() -> tuple[str, ...]:
    return tuple(path.stem for path in _module_paths() if _is_host_module(path.stem))


def _core_modules() -> tuple[Path, ...]:
    return tuple(
        path for path in _module_paths()
        if not _is_host_module(path.stem) and path.stem != DECLARED_SEAM
    )


def _imported_modules(path: Path) -> set[str]:
    """Read the source rather than importing it, because an import would run module-level code."""
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            names.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return names


@pytest.mark.parametrize("path", _core_modules(), ids=lambda path: path.stem)
def test_no_core_module_imports_a_host_module(path: Path) -> None:
    """Lock the direction because one edge back into a host makes that host mandatory for every other."""
    reached = _imported_modules(path) & set(_host_modules())

    assert not reached, f"{path.stem} imports host modules {sorted(reached)}"


KNOWN_ADAPTERS = frozenset({
    "claude_cache", "claude_luna", "claude_native", "claude_presets", "claude_quarantine",
    "codex_luna",
})


def test_every_adapter_on_disk_is_a_known_one() -> None:
    """Compare as a subset because a vendored runtime carries one host's adapters and none of the rest."""
    unknown = set(_host_modules()) - KNOWN_ADAPTERS

    assert not unknown, f"undeclared adapters {sorted(unknown)}"


def _names_a_host(filename: str) -> bool:
    """Split on separators because a substring match calls prompt_submit.py an OMP file."""
    return bool(set(re.split(r"[-_.]", filename)) & set(host.SUPPORTED))


def _core_entry_scripts() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path for path in HOOKS_DIR.glob("*.py")
            if not path.name.startswith("test_") and not _names_a_host(path.name)
        )
    )


@pytest.mark.parametrize("path", _core_entry_scripts(), ids=lambda path: path.stem)
def test_no_shared_entry_script_imports_a_host_module(path: Path) -> None:
    """Cover the entry layer because a hook script every host runs is the worst place to hard-code one."""
    reached = _imported_modules(path) & set(_host_modules())

    assert not reached, f"{path.name} imports host modules {sorted(reached)}"


def test_only_the_declared_seam_reaches_a_host() -> None:
    """Name the one exemption because an unlisted second seam would reopen the coupling silently."""
    seam = LIB_DIR / f"{DECLARED_SEAM}.py"

    assert _imported_modules(seam) & KNOWN_ADAPTERS <= {"codex_luna"}


def test_the_collector_names_no_host_and_no_state_directory() -> None:
    """Keep the reader ignorant because a branch on a host name rebuilds the coupling the split removes."""
    source = (LIB_DIR / "collector.py").read_text(encoding="utf-8")

    for forbidden in (*host.SUPPORTED, ".adw"):
        assert forbidden not in source, f"collector.py names {forbidden}"
