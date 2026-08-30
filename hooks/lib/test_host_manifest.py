from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import host, host_manifest
from lib.test_core_boundary import _core_entry_scripts, _host_modules, _names_a_host


HOOKS_DIR = Path(__file__).parents[1]


def _declared_adapters() -> set[str]:
    return {name for entry in host_manifest.load_all() for name in entry.adapters}


def _declared_entry_scripts() -> set[str]:
    return {name for entry in host_manifest.load_all() for name in entry.entry_scripts}


def test_every_supported_host_ships_a_manifest() -> None:
    """Cover the roster because a host without a manifest cannot be offered or installed."""
    assert host_manifest.available() == host.SUPPORTED


def test_a_vendored_runtime_offers_only_the_host_it_shipped_with(tmp_path: Path) -> None:
    """Tolerate the absent three because the split deletes them, and a crash there would block the install."""
    folder = tmp_path / host.CODEX
    folder.mkdir()
    source = host_manifest.hosts_root() / host.CODEX / host_manifest.MANIFEST_LEAF
    (folder / host_manifest.MANIFEST_LEAF).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    assert host_manifest.available(tmp_path) == (host.CODEX,)
    assert tuple(entry.name for entry in host_manifest.load_all(tmp_path)) == (host.CODEX,)


def test_a_broken_manifest_still_raises_while_an_absent_one_does_not(tmp_path: Path) -> None:
    """Separate the two because a malformed manifest is a defect and a missing one is the design."""
    folder = tmp_path / host.CODEX
    folder.mkdir()
    (folder / host_manifest.MANIFEST_LEAF).write_text("{ not json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        host_manifest.load_all(tmp_path)


def test_the_manifests_claim_every_host_adapter_on_disk() -> None:
    """Compare as a subset because a vendored runtime keeps one host's adapters and all four manifests."""
    unclaimed = set(_host_modules()) - _declared_adapters()

    assert not unclaimed, f"no manifest claims {sorted(unclaimed)}"


def test_the_manifests_claim_every_host_entry_script_on_disk() -> None:
    """Partition the scripts because an unclaimed one would ship to hosts that cannot run it."""
    on_disk = {
        path.name for path in HOOKS_DIR.glob("*.py")
        if not path.name.startswith("test_") and _names_a_host(path.name)
    }

    assert not on_disk - _declared_entry_scripts(), f"no manifest claims {sorted(on_disk - _declared_entry_scripts())}"


def test_no_two_hosts_claim_the_same_file() -> None:
    """Refuse an overlap because two owners means neither runtime can be deleted cleanly."""
    claimed: list[str] = []
    for entry in host_manifest.load_all():
        claimed.extend((*entry.adapters, *entry.entry_scripts))

    assert len(claimed) == len(set(claimed))


def test_a_shared_entry_script_belongs_to_no_host() -> None:
    """Keep the shared layer unclaimed because every runtime needs it, so no single host may own it."""
    shared = {path.name for path in _core_entry_scripts()}

    assert not shared & _declared_entry_scripts()


def test_only_hosts_with_an_installer_reach_the_picker() -> None:
    """Cowork carries none, because its plugins sync from the account rather than from a local script."""
    assert tuple(entry.name for entry in host_manifest.installable()) == (
        host.CLAUDE, host.CODEX, host.OMP,
    )


def test_every_host_names_what_it_writes() -> None:
    """Require the wording because the picker must tell a reader what lands on disk before they choose."""
    for entry in host_manifest.load_all():
        assert entry.writes, f"{entry.name} declares no writes"
        assert entry.title and entry.summary, f"{entry.name} lacks reader-facing wording"


def test_every_declared_installer_exists_and_runs() -> None:
    """Check the file because a manifest naming a missing script sends the router into a dead end."""
    for entry in host_manifest.installable():
        script = host_manifest.hosts_root() / entry.name / entry.installer

        assert script.is_file(), f"{entry.name} names {entry.installer}, which is absent"
        assert os.access(script, os.X_OK), f"{entry.name} installer is not executable"


def test_a_host_without_an_installer_ships_no_script() -> None:
    """Keep the folder empty because a script there would contradict the manifest the router reads."""
    for entry in host_manifest.load_all():
        if entry.installer:
            continue
        folder = host_manifest.hosts_root() / entry.name

        assert not list(folder.glob("*.sh")), f"{entry.name} declares no installer but ships one"


def test_an_unsupported_host_is_refused_rather_than_guessed() -> None:
    """Refuse rather than default because a guessed manifest installs a surface nobody declared."""
    with pytest.raises(ValueError):
        host_manifest.load("some-future-host")


def test_a_manifest_missing_a_field_is_named_rather_than_silently_partial(tmp_path: Path) -> None:
    """Name the gap because a partial manifest would install a host with no declared write surface."""
    broken = tmp_path / host.CODEX
    broken.mkdir()
    (broken / host_manifest.MANIFEST_LEAF).write_text(
        json.dumps({"name": host.CODEX, "title": "Codex"}), encoding="utf-8",
    )

    with pytest.raises(ValueError, match="omits"):
        host_manifest.load(host.CODEX, tmp_path)


def test_a_manifest_declaring_a_foreign_name_is_refused(tmp_path: Path) -> None:
    """Match the directory because a mismatched name would install the wrong host's surface."""
    folder = tmp_path / host.CODEX
    folder.mkdir()
    payload = {field: "x" for field in host_manifest.REQUIRED_FIELDS}
    payload.update({
        "name": host.OMP, "adapters": [], "entry_scripts": [],
        "writes": [], "installer": None, "extra_paths": [],
    })
    (folder / host_manifest.MANIFEST_LEAF).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="declares the name"):
        host_manifest.load(host.CODEX, tmp_path)
