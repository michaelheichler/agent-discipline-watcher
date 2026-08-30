"""Read from disk rather than hard-coded, because the installer router and the vendor build must agree on one roster."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

try:
    from . import host
except ImportError:
    import host


MANIFEST_LEAF = "host.json"
REQUIRED_FIELDS = (
    "name", "title", "summary", "adapters", "entry_scripts",
    "installer", "installer_note", "writes", "extra_paths",
)


class HostManifest(NamedTuple):
    """Carry the install surface beside the code surface because the picker must name what a host writes."""

    name: str
    title: str
    summary: str
    adapters: tuple[str, ...]
    entry_scripts: tuple[str, ...]
    installer: str | None
    installer_note: str
    writes: tuple[str, ...]
    extra_paths: tuple[str, ...]


def hosts_root(root: str | Path | None = None) -> Path:
    """Resolve from this file because a vendored runtime carries its own copy at the same depth."""
    return Path(root) if root is not None else Path(__file__).parents[2] / "hosts"


def _parse(row: Any, name: str) -> HostManifest:
    if not isinstance(row, dict):
        raise ValueError(f"host manifest for {name} must be an object")
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
        raise ValueError(f"host manifest for {name} omits {', '.join(sorted(missing))}")
    if row["name"] != name:
        raise ValueError(f"host manifest in {name} declares the name {row['name']}")
    installer = row["installer"]
    if installer is not None and not isinstance(installer, str):
        raise ValueError(f"host manifest for {name} declares a non-string installer")
    return HostManifest(
        name=row["name"],
        title=row["title"],
        summary=row["summary"],
        adapters=tuple(row["adapters"]),
        entry_scripts=tuple(row["entry_scripts"]),
        installer=installer,
        installer_note=row["installer_note"],
        writes=tuple(row["writes"]),
        extra_paths=tuple(row["extra_paths"]),
    )


def load(name: str, root: str | Path | None = None) -> HostManifest:
    """Refuse an unknown name because a guessed manifest would install a surface nobody declared."""
    if name not in host.SUPPORTED:
        raise ValueError(f"{name} is not a supported host")
    path = hosts_root(root) / name / MANIFEST_LEAF
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"host manifest for {name} is unreadable: {exc}") from exc
    return _parse(row, name)


def available(root: str | Path | None = None) -> tuple[str, ...]:
    """Read what is on disk because a vendored runtime ships its own manifest and none of the others."""
    base = hosts_root(root)
    return tuple(name for name in host.SUPPORTED if (base / name / MANIFEST_LEAF).is_file())


def load_all(root: str | Path | None = None) -> tuple[HostManifest, ...]:
    """Skip an absent manifest but never a broken one, because absence is the split working as designed."""
    return tuple(load(name, root) for name in available(root))


def installable(root: str | Path | None = None) -> tuple[HostManifest, ...]:
    """Filter on the installer because a host without one has nothing for the picker to run."""
    return tuple(entry for entry in load_all(root) if entry.installer)
