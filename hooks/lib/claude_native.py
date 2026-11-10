"""Keep settings updates durable because interrupted hooks must recover safely."""
from __future__ import annotations
# pylint: disable=too-many-lines,too-few-public-methods,too-many-branches,too-many-statements,unidiomatic-typecheck
# Keep descriptor checks together because recovery shares their invariants.

import json
from contextlib import contextmanager
import fcntl
import hashlib
import os
import stat
from pathlib import Path

try:
    from . import config_roots as config_paths
except ImportError:
    import config_roots as config_paths

try:
    from . import state_recovery
    from .secure_fs import (
        LEAF_FLAGS as _LEAF_FLAGS, MetadataKey, close_quietly as _close_quietly,
        metadata_key as _metadata_key, open_parent as _open_parent,
        open_unchanged as _open_unchanged, read_verified,
    )
except ImportError:
    import state_recovery
    from secure_fs import (
        LEAF_FLAGS as _LEAF_FLAGS, MetadataKey, close_quietly as _close_quietly,
        metadata_key as _metadata_key, open_parent as _open_parent,
        open_unchanged as _open_unchanged, read_verified,
    )
from typing import Any, Callable, Iterator, Mapping

try:
    from . import claude_presets, claude_transaction, judge_status
    from .claude_lifecycle import LunaOperations, LunaSettings
except ImportError:
    import claude_presets
    import claude_transaction
    import judge_status
    from claude_lifecycle import LunaOperations, LunaSettings


Generation = tuple[str | None, MetadataKey | None]
PRESETS = claude_presets.PRESETS
# Mapped, because a dropped name reads as no preset.
RETIRED_PRESETS = {"mixed": "luna", "sonnet": "luna", "haiku": "luna", "luna-native": "luna"}
REMOTE_ENV = "CLAUDE_CODE_REMOTE"
PRESET_ENV = "ADW_CLAUDE_PRESET"
SETTINGS_ENV = "ADW_CLAUDE_SETTINGS"
PRESET_FILE_ENV = "ADW_CLAUDE_PRESET_FILE"
MANAGED_MARKER = "adw-managed-hook-v1"
TRANSACTION_SUFFIX = ".txn"
LOCK_SUFFIX = ".lock"
TRANSACTION_VERSION = 2
CORRUPT_SUFFIX = ".corrupt-"
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_CORRUPT_QUARANTINES = 8
MAX_CORRUPT_QUARANTINE_BYTES = 2 * MAX_STATE_BYTES
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"


class _SettingsChanged(RuntimeError):
    """Retry because settings changed during a guarded atomic update."""


_validate_preset = claude_presets.validate_preset


def preset_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(PRESET_FILE_ENV, str(config_paths.data_root() / "claude" / "preset"))).expanduser()


def settings_path(environment: Mapping[str, str] | None = None) -> Path:
    try:
        from . import claude_cache
    except ImportError:
        import claude_cache

    env = os.environ if environment is None else environment
    if SETTINGS_ENV in env:
        return Path(env[SETTINGS_ENV]).expanduser()
    roots = claude_cache.config_roots(dict(env))
    override = env.get(claude_cache.CONFIG_ENV, "").strip()
    root = Path(override) if override else next(iter(roots), config_paths.home_root() / ".claude")
    return root / "settings.json"


def _settings_target(path: str | Path | None) -> Path:
    """Named apart, because a public keyword called settings_path hides the function of that name."""
    return _canonical(settings_path() if path is None else path)


def _preset_target(path: str | Path | None) -> Path:
    return _canonical(preset_path() if path is None else path)


def _lexical(path: str | Path) -> Path:
    """Keep symlinks unresolved because parents need descriptor-safe checks."""
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = Path.cwd() / value
    return Path(os.path.abspath(os.fspath(value)))


def _canonical(path: str | Path) -> Path:
    # Keep this seam because callers must not follow symlinked parents.
    return _lexical(path)


def _transaction_path(path: str | Path) -> Path:
    target = _canonical(path)
    return target.with_name(target.name + TRANSACTION_SUFFIX)


def _lock_path(path: str | Path) -> Path:
    target = _canonical(path)
    return target.with_name(target.name + LOCK_SUFFIX)


def _unlink_quietly(parent_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        pass


def _leaf_lstat(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


@contextmanager
def _preset_lock(path: str | Path) -> Iterator[None]:
    lock = _lock_path(path)
    parent_fd = _open_parent(lock, create=True)
    try:
        descriptor = os.open(
            lock.name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600,
            dir_fd=parent_fd,
        )
    except BaseException:
        os.close(parent_fd)
        raise
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"preset lock is not a regular file: {lock}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
        os.close(parent_fd)


def _read_preset_unlocked(path: Path) -> str | None:
    try:
        text = _read_regular_text(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if text is None:
        return None
    value = text.strip()
    if value in PRESETS:
        return value
    return RETIRED_PRESETS.get(value)


def _read_regular_data(path: Path, *, allow_final_symlink: bool = False) -> tuple[str, MetadataKey] | None:
    target = _lexical(path)
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = _open_parent(target, create=False)
        leaf = _leaf_lstat(parent_fd, target.name)
        if leaf is None:
            return None
        descriptor, opened = _open_state_leaf(parent_fd, target, leaf, allow_final_symlink)
        data, after = read_verified(descriptor, opened, MAX_STATE_BYTES)
        if allow_final_symlink and stat.S_ISLNK(leaf.st_mode):
            _require_same_link_target(parent_fd, target, opened)
        return data.decode("utf-8"), _metadata_key(after)
    finally:
        _close_quietly(descriptor)
        _close_quietly(parent_fd)


def _open_state_leaf(parent_fd: int, target: Path, leaf: os.stat_result, allow_final_symlink: bool) -> tuple[int, os.stat_result]:
    if stat.S_ISREG(leaf.st_mode):
        flags = os.O_RDONLY | os.O_NONBLOCK | _LEAF_FLAGS
        return _open_unchanged(parent_fd, target.name, flags, leaf, f"preset state leaf changed while reading: {target}")
    if not stat.S_ISLNK(leaf.st_mode):
        raise ValueError(f"preset state leaf is not a regular file: {target}")
    if not allow_final_symlink:
        raise ValueError(f"preset state leaf is not safely readable: {target}")
    before = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=True)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"preset state symlink target is not a regular file: {target}")
    flags = os.O_RDONLY | os.O_NONBLOCK
    return _open_unchanged(parent_fd, target.name, flags, before, f"preset state symlink target changed while reading: {target}")


def _require_same_link_target(parent_fd: int, target: Path, opened: os.stat_result) -> None:
    current_target = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=True)
    if _metadata_key(current_target) != _metadata_key(opened):
        raise ValueError(f"preset state symlink target changed while reading: {target}")


def _read_regular_text(path: Path, *, allow_final_symlink: bool = False) -> str | None:
    data = _read_regular_data(path, allow_final_symlink=allow_final_symlink)
    return data[0] if data is not None else None


def _unlink_transaction(path: Path) -> None:
    transaction = _transaction_path(path)
    parent_fd = _open_parent(transaction, create=False)
    try:
        try:
            os.unlink(transaction.name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    finally:
        os.close(parent_fd)


def _quarantine_transaction(path: Path) -> None:
    """Only the exact bad leaf moves aside, because following it would take the settings with it."""
    claude_transaction.quarantine(
        _transaction_path(path),
        lambda target: _open_parent(target, create=False),
        CORRUPT_SUFFIX,
        MAX_CORRUPT_QUARANTINES,
        MAX_CORRUPT_QUARANTINE_BYTES,
    )


def _transaction_payload(path: Path) -> dict[str, Any] | None:
    text = _read_regular_text(_transaction_path(path))
    if text is None:
        return None
    return claude_transaction.validate_payload(text, PRESETS, TRANSACTION_VERSION)


_managed_hooks = claude_presets.managed_hooks
_managed_hash = claude_presets.managed_hash
_preset_managed_hash = claude_presets.preset_managed_hash


def _settings_snapshot(path: Path) -> tuple[str | None, dict[str, Any], MetadataKey | None]:
    data = _read_regular_data(path, allow_final_symlink=True)
    text = data[0] if data is not None else None
    generation = data[1] if data is not None else None
    if text is None:
        return None, {}, None
    try:
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read Claude settings: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Claude settings must be a JSON object")
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), value, generation


def _recover_unlocked(settings: Path, preset: Path) -> None:
    try:
        payload = _transaction_payload(preset)
    except (OSError, ValueError):
        _quarantine_transaction(preset)
        return
    if payload is None:
        return
    current_preset = _read_preset_unlocked(preset)
    if current_preset not in {payload["base_preset"], str(payload["preset"])}:
        _quarantine_transaction(preset)
        return
    _replay_transaction(settings, preset, payload, current_preset)


def _replay_transaction(settings: Path, preset: Path, payload: dict[str, Any], current_preset: str | None) -> None:
    desired = str(payload["preset"])
    current_hash, current_settings, current_generation = _settings_snapshot(settings)
    current_managed_hash = _managed_hash(current_settings)
    base_managed_hash = payload.get("base_managed_hash") or _preset_managed_hash(payload["base_preset"])
    if current_managed_hash == _preset_managed_hash(desired):
        # Finish only bookkeeping because settings already include external edits.
        if current_preset != desired:
            _atomic_write(preset, desired + "\n")
        _unlink_transaction(preset)
        return
    if current_managed_hash != base_managed_hash:
        _quarantine_transaction(preset)
        return
    rendered = _render_for_preset(current_settings, desired)
    try:
        _atomic_write_settings(settings, rendered, expected_generation=(current_hash, current_generation))
    except _SettingsChanged:
        # Leave recovery to callers because they can merge the newer generation.
        _quarantine_transaction(preset)
        return
    _atomic_write(preset, desired + "\n")
    _unlink_transaction(preset)


def _recover(
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> None:
    target_preset = _preset_target(preset_path)
    target_settings = _settings_target(settings_path)
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)


def recover(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None) -> None:
    """Replay durable transitions because a writer may stop between settings updates."""
    _recover(settings_path=settings_path, preset_path=preset_path)


def _settings_generation(path: Path) -> Generation:
    digest, _settings, metadata = _settings_snapshot(path)
    return digest, metadata


@contextmanager
def luna_settings_gate(
    *, settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> Iterator[LunaSettings | None]:
    """Hold the snapshot stable because a provider must start against its reserved settings."""
    target_preset = _preset_target(preset_path)
    target_settings = _settings_target(settings_path)
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        if _read_preset_unlocked(target_preset) != "luna":
            yield None
        else:
            generation = (*_settings_generation(target_settings), _read_regular_text(target_preset))
            yield LunaSettings(target_settings, target_preset, generation)


luna_operation = LunaOperations(luna_settings_gate)


def read_preset(
    path: str | Path | None = None,
    *,
    settings_path: str | Path | None = None,
) -> str | None:
    target = _preset_target(path)
    target_settings = _settings_target(settings_path)
    with _preset_lock(target):
        try:
            _recover_unlocked(target_settings, target)
        except (OSError, ValueError):
            return None
        return _read_preset_unlocked(target)


def _default_preset_unlocked(env: Mapping[str, str], target_preset: Path) -> str:
    explicit = env.get(PRESET_ENV, "").strip()
    if explicit:
        return _validate_preset(RETIRED_PRESETS.get(explicit, explicit))
    stored = _read_preset_unlocked(target_preset)
    if stored is not None:
        return stored
    return "luna"


def default_preset(
    environment: Mapping[str, str] | None = None,
    *,
    preset_path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> str:
    env = os.environ if environment is None else environment
    target_preset = _preset_target(preset_path)
    target_settings = _settings_target(settings_path)
    with _preset_lock(target_preset):
        try:
            _recover_unlocked(target_settings, target_preset)
        except (OSError, ValueError):
            pass
        return _default_preset_unlocked(env, target_preset)


generated_hooks = claude_presets.generated_hooks


def settings_for_preset(settings: object, preset: str) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("Claude settings must be a JSON object")
    selected = _validate_preset(preset)
    merged = claude_presets.without_managed(dict(settings))
    hooks = dict(merged.get("hooks")) if isinstance(merged.get("hooks"), dict) else {}
    for lifecycle, groups in generated_hooks(selected).items():
        existing = hooks.get(lifecycle)
        hooks[lifecycle] = list(existing) if isinstance(existing, list) else []
        hooks[lifecycle].extend(groups)
    merged["hooks"] = hooks
    return merged


def _render_for_preset(settings: object, preset: str) -> str:
    return json.dumps(settings_for_preset(settings, preset), indent=2, sort_keys=True) + "\n"


def _load_settings(path: Path) -> dict[str, Any]:
    return _settings_snapshot(path)[1]


def _atomic_write_settings(
    path: Path,
    text: str,
    *,
    expected_generation: Generation | None = None,
) -> None:
    """Preserve final aliases because settings may link to another regular file."""
    target = _lexical(path)
    alias = _write_unless_alias(target, text, expected_generation)
    if alias is None:
        return
    link_target, resolved_target = alias
    _atomic_write(resolved_target, text, expected_generation=expected_generation)
    _verify_alias(target, link_target, resolved_target)


def _write_unless_alias(
    target: Path,
    text: str,
    expected_generation: Generation | None,
) -> tuple[str, Path] | None:
    parent_fd = _open_parent(target, create=True)
    try:
        leaf = _leaf_lstat(parent_fd, target.name)
        if leaf is None or not stat.S_ISLNK(leaf.st_mode):
            _atomic_write_regular_open(
                parent_fd, target.name, leaf, text, expected_generation=expected_generation,
            )
            return None
        link_target = os.readlink(target.name, dir_fd=parent_fd)
        before = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=True)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"preset settings symlink target is not a regular file: {target}")
    finally:
        os.close(parent_fd)
    return link_target, _lexical(Path(link_target) if os.path.isabs(link_target) else target.parent / link_target)


def _verify_alias(target: Path, link_target: str, resolved_target: Path) -> None:
    verify_parent = _open_parent(target, create=False)
    try:
        if os.readlink(target.name, dir_fd=verify_parent) != link_target:
            raise ValueError(f"preset settings symlink changed while writing: {target}")
        after = os.stat(target.name, dir_fd=verify_parent, follow_symlinks=True)
        target_after = _stat_leaf(resolved_target)
        if not stat.S_ISREG(after.st_mode) or _metadata_key(after) != _metadata_key(target_after):
            raise ValueError(f"preset settings symlink target changed while writing: {target}")
    finally:
        os.close(verify_parent)


def _stat_leaf(path: Path) -> os.stat_result:
    parent_fd = _open_parent(path, create=False)
    try:
        return os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(parent_fd)


def _atomic_write(
    path: Path,
    text: str,
    *,
    expected_generation: Generation | None = None,
) -> None:
    target = _lexical(path)
    parent_fd = _open_parent(target, create=True)
    try:
        leaf = _leaf_lstat(parent_fd, target.name)
        _atomic_write_regular_open(parent_fd, target.name, leaf, text, expected_generation=expected_generation)
    finally:
        os.close(parent_fd)


def _regular_generation(
    parent_fd: int,
    name: str,
) -> Generation:
    descriptor = -1
    try:
        leaf = _leaf_lstat(parent_fd, name)
        if leaf is None:
            return None, None
        if not stat.S_ISREG(leaf.st_mode):
            return "", _metadata_key(leaf)
        descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _LEAF_FLAGS, dir_fd=parent_fd)
        return _descriptor_generation(descriptor, leaf, name)
    except (OSError, UnicodeError) as exc:
        raise _SettingsChanged(f"settings target could not be checked while writing: {name}") from exc
    finally:
        _close_quietly(descriptor)


def _descriptor_generation(descriptor: int, leaf: os.stat_result, name: str) -> tuple[str, MetadataKey]:
    try:
        data, after = read_verified(descriptor, leaf, MAX_STATE_BYTES)
    except ValueError as error:
        raise _SettingsChanged(f"settings target changed while writing: {name}") from error
    return hashlib.sha256(data).hexdigest(), _metadata_key(after)


def _atomic_write_regular_open(
    parent_fd: int,
    name: str,
    leaf: os.stat_result | None,
    text: str,
    *,
    expected_generation: Generation | None = None,
) -> None:
    if leaf is not None and not stat.S_ISREG(leaf.st_mode):
        raise ValueError(f"preset state leaf is not a regular file: {name}")
    mode = leaf.st_mode & 0o777 if leaf is not None else 0o600

    def check_replacement() -> None:
        # Refuse replacement because a changed leaf may redirect the write.
        current = _leaf_lstat(parent_fd, name)
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise ValueError(f"preset state leaf is not a regular file: {name}")
        if expected_generation is not None and _regular_generation(parent_fd, name) != expected_generation:
            raise _SettingsChanged(f"settings target changed while writing: {name}")

    with state_recovery.atomic_open(
        Path(name), parent_fd=parent_fd, mode=mode, sync=True, before_replace=check_replacement,
    ) as stream:
        stream.write(text)


def _transaction_record(
    selected: str,
    base_preset: str | None,
    current: dict[str, Any],
    base: Generation,
) -> str:
    base_hash, base_generation = base
    return json.dumps({
        "version": TRANSACTION_VERSION,
        "preset": selected,
        "base_preset": base_preset,
        "base_settings_hash": base_hash,
        "base_settings_metadata": list(base_generation) if base_generation is not None else None,
        "base_managed_hash": _managed_hash(current),
    }, indent=2, sort_keys=True) + "\n"


def _set_preset_unlocked(selected: str, target_settings: Path, target_preset: Path) -> str:
    for _attempt in range(3):
        base_hash, current, base_generation = _settings_snapshot(target_settings)
        base = (base_hash, base_generation)
        base_preset = _read_preset_unlocked(target_preset)
        rendered = _render_for_preset(current, selected)
        _atomic_write(_transaction_path(target_preset), _transaction_record(selected, base_preset, current, base))
        try:
            _atomic_write_settings(_canonical(target_settings), rendered, expected_generation=base)
        except _SettingsChanged:
            continue
        _atomic_write(_canonical(target_preset), selected + "\n")
        _unlink_transaction(target_preset)
        return selected
    raise _SettingsChanged("settings target changed repeatedly; refusing to overwrite newer changes")


def set_preset(
    preset: str,
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> str:
    selected = _validate_preset(preset)
    target_settings = _settings_target(settings_path)
    target_preset = _preset_target(preset_path)
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        return _set_preset_unlocked(selected, target_settings, target_preset)


def ensure_managed_block(
    default: str,
    repoint: Callable[[dict[str, Any]], dict[str, Any]],
    is_retired: Callable[[dict[str, Any]], bool],
    *,
    settings_file: str | Path | None = None,
    preset_file: str | Path | None = None,
) -> str | None:
    """One lock, because a racing set_preset must not interleave."""
    target_settings = _settings_target(settings_file)
    target_preset = _preset_target(preset_file)
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        current = _load_settings(target_settings)
        if not _managed_hooks(current) or is_retired(current):
            return _set_preset_unlocked(default, target_settings, target_preset)
        _rewrite_settings(target_settings, repoint)
        return None


def _rewrite_settings(path: Path, transform: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    digest, current, generation = _settings_snapshot(path)
    updated = transform(current)
    if updated == current:
        return
    rendered = json.dumps(updated, indent=2, sort_keys=True) + "\n"
    _atomic_write_settings(path, rendered, expected_generation=(digest, generation))


def status(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    target_settings = _settings_target(settings_path)
    target_preset = _preset_target(preset_path)
    env = os.environ if environment is None else environment
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        selected = _read_preset_unlocked(target_preset)
        stored = selected is not None
        if selected is None:
            selected = _default_preset_unlocked(env, target_preset)
    seen = judge_status.plugin_reviewers() + judge_status.settings_reviewers(target_settings, claude_presets.is_managed_hook)
    return {
        **judge_status.describe(selected, stored, seen),
        "settings": str(settings_path or target_settings),
        "watch": "settings-only changes are watched automatically; reload plugins after plugin install or source updates",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="adw-judge")
    parser.add_argument("preset", choices=(*PRESETS, "status"))
    args = parser.parse_args(argv)
    try:
        if args.preset == "status":
            print(json.dumps(status(), sort_keys=True))
        else:
            selected = set_preset(args.preset)
            print(f"ADW Claude preset: {selected}. Settings-only changes are watched automatically; /reload-plugins is for plugin install or source updates.")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"adw-judge: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
