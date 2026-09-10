from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MISSING = object()


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    content: bytes = b""
    mode: int = 0o600


def snapshots(config_root: Path, catalog_path: Path) -> dict[Path, FileSnapshot]:
    paths = (
        catalog_path,
        config_root / "settings.json",
        config_root / "plugins" / "known_marketplaces.json",
        config_root / "plugins" / "installed_plugins.json",
    )
    return {path: snapshot(path) for path in paths}


def snapshot(path: Path) -> FileSnapshot:
    if not os.path.lexists(path):
        return FileSnapshot(False)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"state path is not a regular file: {path}")
    return FileSnapshot(True, path.read_bytes(), stat.S_IMODE(metadata.st_mode))


def mkdir_safe(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts:
        if part in (path.anchor, ""):
            continue
        current /= part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ValueError(f"state directory is not safe: {current}")
            continue
        current.mkdir(mode=0o700)


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    mkdir_safe(path.parent)
    if os.path.lexists(path) and path.is_symlink():
        raise ValueError(f"state path is a symlink: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    except BaseException:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def rollback(
    config_root: Path,
    catalog_path: Path,
    saved: Mapping[Path, FileSnapshot],
    marketplace_name: str,
    plugin_id: str,
) -> None:
    _restore_catalog(catalog_path, saved[catalog_path])
    settings = config_root / "settings.json"
    _restore_json_member(settings, saved[settings], "extraKnownMarketplaces", marketplace_name)
    _restore_json_member(settings, saved[settings], "enabledPlugins", plugin_id)
    known = config_root / "plugins" / "known_marketplaces.json"
    _restore_json_member(known, saved[known], None, marketplace_name)
    installed = config_root / "plugins" / "installed_plugins.json"
    _restore_json_member(installed, saved[installed], "plugins", plugin_id)


def _restore_catalog(path: Path, saved: FileSnapshot) -> None:
    if saved.exists:
        atomic_write(path, saved.content, saved.mode)
        return
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"cannot remove unsafe catalog path: {path}")
        path.unlink()
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break


def _restore_json_member(path: Path, saved: FileSnapshot, section: str | None, key: str) -> None:
    current = _rollback_current(path, saved)
    if current is None:
        return
    before = _json_snapshot(saved)
    if before is None:
        _restore_snapshot(path, saved)
        return
    if not _reconcile_member(current, before, section, key):
        _restore_snapshot(path, saved)
        return
    if not saved.exists and not current:
        _remove_state_file(path)
        return
    _atomic_write_json(path, current, saved.mode)


def _rollback_current(path: Path, saved: FileSnapshot) -> dict[str, Any] | None:
    if not os.path.lexists(path):
        if saved.exists:
            _restore_snapshot(path, saved)
        return None
    try:
        return _read_json(path)
    except RuntimeError:
        _restore_snapshot(path, saved)
        return None


def _reconcile_member(current: dict[str, Any], before: dict[str, Any], section: str | None, key: str) -> bool:
    if section is None:
        return _reconcile_section(current, before, key)
    current_section = current.get(section)
    before_section = before.get(section, MISSING)
    if not isinstance(current_section, dict):
        if current_section is None and before_section is MISSING:
            _restore_missing_root(current, before, section)
            return True
        return False
    if not _reconcile_section(current_section, before_section, key):
        return False
    if before_section is MISSING and not current_section:
        current.pop(section, None)
    _restore_missing_root(current, before, section)
    return True


def _reconcile_section(current_section: dict[str, Any], before_section: Any, key: str) -> bool:
    if before_section is MISSING:
        current_section.pop(key, None)
        return True
    if isinstance(before_section, dict):
        previous = before_section.get(key, MISSING)
        if previous is MISSING:
            current_section.pop(key, None)
        else:
            current_section[key] = previous
        for name, value in before_section.items():
            if name != key and name not in current_section:
                current_section[name] = value
    else:
        return False
    return True


def _restore_missing_root(current: dict[str, Any], before: dict[str, Any], section: str) -> None:
    for name, value in before.items():
        if name != section and name not in current:
            current[name] = value


def _json_snapshot(saved: FileSnapshot) -> dict[str, Any] | None:
    if not saved.exists:
        return {}
    try:
        value = json.loads(saved.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _restore_snapshot(path: Path, saved: FileSnapshot) -> None:
    if saved.exists:
        atomic_write(path, saved.content, saved.mode)
    else:
        _remove_state_file(path)


def _remove_state_file(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"cannot remove unsafe state path: {path}")
    path.unlink()


def _atomic_write_json(path: Path, value: dict[str, Any], mode: int) -> None:
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), mode)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Claude state file is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Claude state file is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Claude state file is not a JSON object: {path}")
    return value


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
