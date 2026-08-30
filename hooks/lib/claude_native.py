"""Generate and manage ADW's native Claude model-review hook block."""
from __future__ import annotations
# pylint: disable=too-many-lines,too-few-public-methods,too-many-branches,too-many-statements,unidiomatic-typecheck
# The native settings adapter keeps its descriptor transaction and rollback invariants together.

import json
from contextlib import contextmanager
import fcntl
import hashlib
import os
import re
import secrets
import shlex
import stat
import threading
from pathlib import Path
from typing import Any, Iterator, Mapping


PRESETS = ("mixed", "luna", "haiku", "sonnet")
REMOTE_ENV = "CLAUDE_CODE_REMOTE"
HAIKU_ONLY_ENV = "ADW_CLAUDE_HAIKU_ONLY"
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
MAX_FAILURE_MESSAGE = 256
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"
JOURNAL_READER_PATH = shlex.quote(str(PLUGIN_ROOT / "hooks" / "read_claude_journal.sh"))


class _SettingsChanged(RuntimeError):
    """The regular settings target changed during a guarded atomic update."""


class _LunaReservation:
    def __init__(self, settings_path: Path, preset_path: Path, generation: tuple[object, ...]) -> None:
        self.settings_path = settings_path
        self.preset_path = preset_path
        self.generation = generation
        self.token = secrets.token_hex(16)


_LUNA_RESERVATIONS: dict[Path, _LunaReservation] = {}
_LUNA_RESERVATIONS_LOCK = threading.Lock()


def _validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly mixed, luna, haiku, or sonnet")
    return value


def preset_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(PRESET_FILE_ENV, str(Path.home() / ".adw" / "claude" / "preset"))).expanduser()


def settings_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(SETTINGS_ENV, str(Path.home() / ".claude" / "settings.json"))).expanduser()


def _lexical(path: str | Path) -> Path:
    """Normalize a path without resolving any symlink components."""
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = Path.cwd() / value
    return Path(os.path.abspath(os.fspath(value)))


def _canonical(path: str | Path) -> Path:
    # Keep this local naming seam, but do not follow symlinked parents.
    return _lexical(path)


def _transaction_path(path: str | Path) -> Path:
    target = _canonical(path)
    return target.with_name(target.name + TRANSACTION_SUFFIX)


def _lock_path(path: str | Path) -> Path:
    target = _canonical(path)
    return target.with_name(target.name + LOCK_SUFFIX)


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_LEAF_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _open_parent(path: Path, *, create: bool) -> int:
    """Open every parent component with O_NOFOLLOW and return its descriptor."""
    target = _lexical(path)
    if not target.is_absolute():
        raise ValueError(f"path must be absolute: {target}")
    descriptor = os.open(target.anchor or os.sep, _DIRECTORY_FLAGS)
    try:
        for part in target.parent.parts:
            if part in (target.anchor, ""):
                continue
            if part in (".", ".."):
                raise ValueError(f"unsafe path component: {part}")
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    raise ValueError(f"path parent is not a directory: {part}")
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _leaf_lstat(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _metadata_key(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


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
    return value if value in PRESETS else None


def _read_regular_data(path: Path, *, allow_final_symlink: bool = False) -> tuple[str, tuple[int, int, int, int, int, int]] | None:
    target = _lexical(path)
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = _open_parent(target, create=False)
        leaf = _leaf_lstat(parent_fd, target.name)
        if leaf is None:
            return None
        if stat.S_ISLNK(leaf.st_mode):
            if not allow_final_symlink:
                raise ValueError(f"preset state leaf is not safely readable: {target}")
            before = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=True)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"preset state symlink target is not a regular file: {target}")
            descriptor = os.open(target.name, os.O_RDONLY | os.O_NONBLOCK, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            if _metadata_key(opened) != _metadata_key(before):
                raise ValueError(f"preset state symlink target changed while reading: {target}")
        elif stat.S_ISREG(leaf.st_mode):
            descriptor = os.open(target.name, os.O_RDONLY | os.O_NONBLOCK | _LEAF_FLAGS, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            if _metadata_key(opened) != _metadata_key(leaf):
                raise ValueError(f"preset state leaf changed while reading: {target}")
        else:
            raise ValueError(f"preset state leaf is not a regular file: {target}")
        if opened.st_size > MAX_STATE_BYTES:
            raise ValueError(f"preset state leaf is too large: {target}")
        data = bytearray()
        while len(data) <= MAX_STATE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_STATE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_STATE_BYTES:
            raise ValueError(f"preset state leaf is too large: {target}")
        after = os.fstat(descriptor)
        if _metadata_key(after) != _metadata_key(opened) or len(data) != after.st_size:
            raise ValueError(f"preset state leaf changed while reading: {target}")
        if allow_final_symlink and stat.S_ISLNK(leaf.st_mode):
            current_target = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=True)
            if _metadata_key(current_target) != _metadata_key(opened):
                raise ValueError(f"preset state symlink target changed while reading: {target}")
        return bytes(data).decode("utf-8"), _metadata_key(after)
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except OSError:
                pass


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
    """Move only the exact bad transaction leaf aside, without following it."""
    transaction = _transaction_path(path)
    prefix = transaction.name[:64] or "adw.txn"
    parent_fd = -1
    try:
        parent_fd = _open_parent(transaction, create=False)
    except OSError:
        return
    try:
        _reclaim_quarantines(parent_fd, prefix)
        for _attempt in range(32):
            quarantine = f"{prefix}{CORRUPT_SUFFIX}{secrets.token_hex(8)}"
            try:
                os.rename(transaction.name, quarantine, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                _reclaim_quarantines(parent_fd, prefix)
                return
            except FileNotFoundError:
                return
            except FileExistsError:
                continue
            except OSError:
                return
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _owned_quarantine_name(name: str, prefix: str) -> bool:
    token = name[len(prefix + CORRUPT_SUFFIX):] if name.startswith(prefix + CORRUPT_SUFFIX) else ""
    return len(token) == 16 and re.fullmatch(r"[0-9a-f]{16}", token) is not None


def _reclaim_quarantines(parent_fd: int, prefix: str) -> None:
    """Bound only ADW's exact quarantine leaves; never glob or recurse."""
    try:
        names = [name for name in os.listdir(parent_fd) if _owned_quarantine_name(name, prefix)]
    except OSError:
        return
    entries: list[tuple[int, str, int, int]] = []
    for name in names:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError:
            continue
        entries.append((metadata.st_mtime_ns, name, metadata.st_size, metadata.st_mode))
    total = sum(size for _mtime, _name, size, _mode in entries)
    for _mtime, name, size, mode in sorted(entries):
        if len(entries) <= MAX_CORRUPT_QUARANTINES and total <= MAX_CORRUPT_QUARANTINE_BYTES:
            break
        try:
            if stat.S_ISDIR(mode):
                os.rmdir(name, dir_fd=parent_fd)
            elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                os.unlink(name, dir_fd=parent_fd)
            else:
                continue
        except OSError:
            continue
        entries = [entry for entry in entries if entry[1] != name]
        total -= size


def _transaction_payload(path: Path) -> dict[str, Any] | None:
    transaction = _transaction_path(path)
    text = _read_regular_text(transaction)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read preset transaction: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("preset transaction must be a JSON object")
    expected = {"version", "preset", "base_preset", "base_settings_hash"}
    allowed = expected | {"base_managed_hash", "base_settings_metadata"}
    if not set(payload).issubset(allowed) or not expected.issubset(payload) or payload.get("version") != TRANSACTION_VERSION or payload.get("preset") not in PRESETS:
        raise ValueError("invalid preset transaction")
    if payload["base_preset"] is not None and payload["base_preset"] not in PRESETS:
        raise ValueError("invalid base preset in transaction")
    base_hash = payload["base_settings_hash"]
    if base_hash is not None and (
        not isinstance(base_hash, str) or len(base_hash) != 64
        or any(character not in "0123456789abcdef" for character in base_hash)
    ):
        raise ValueError("invalid base settings hash in transaction")
    managed_hash = payload.get("base_managed_hash")
    if managed_hash is not None and (
        not isinstance(managed_hash, str) or len(managed_hash) != 64
        or any(character not in "0123456789abcdef" for character in managed_hash)
    ):
        raise ValueError("invalid base managed hash in transaction")
    metadata = payload.get("base_settings_metadata")
    if metadata is not None and (
        not isinstance(metadata, list) or len(metadata) != 6
        or any(type(value) is not int or value < 0 for value in metadata)
    ):
        raise ValueError("invalid base settings metadata in transaction")
    return payload


def _managed_hooks(settings: object) -> dict[str, list[object]]:
    if not isinstance(settings, dict):
        return {}
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return {}
    managed: dict[str, list[object]] = {}
    for lifecycle, groups in hooks.items():
        if not isinstance(lifecycle, str) or not isinstance(groups, list):
            continue
        entries: list[object] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            entries.extend(hook for hook in group["hooks"] if _is_managed_hook(hook))
        if entries:
            managed[lifecycle] = entries
    return managed


def _managed_hash(settings: object) -> str:
    payload = json.dumps(_managed_hooks(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preset_managed_hash(preset: str | None) -> str:
    hooks = generated_hooks(preset) if preset in PRESETS else {}
    return _managed_hash({"hooks": hooks})


def _settings_snapshot(path: Path) -> tuple[str | None, dict[str, Any], tuple[int, int, int, int, int, int] | None]:
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
    desired = str(payload["preset"])
    base_preset = payload["base_preset"]
    current_preset = _read_preset_unlocked(preset)
    if current_preset not in {base_preset, desired}:
        _quarantine_transaction(preset)
        return
    _current_hash, current_settings, current_generation = _settings_snapshot(settings)
    current_managed_hash = _managed_hash(current_settings)
    desired_managed_hash = _preset_managed_hash(desired)
    base_managed_hash = payload.get("base_managed_hash") or _preset_managed_hash(base_preset)
    if current_managed_hash == desired_managed_hash:
        # The settings half already landed. Preserve unrelated external edits and
        # finish only the remaining preset/txn bookkeeping.
        if current_preset != desired:
            _atomic_write(preset, desired + "\n")
        _unlink_transaction(preset)
        return
    if current_managed_hash != base_managed_hash:
        _quarantine_transaction(preset)
        return
    rendered = json.dumps(settings_for_preset(current_settings, desired), indent=2, sort_keys=True) + "\n"
    try:
        _atomic_write_settings(settings, rendered, expected_generation=(_current_hash, current_generation))
    except _SettingsChanged:
        # A caller will re-read and merge a newer external settings generation.
        _quarantine_transaction(preset)
        return
    _atomic_write(preset, desired + "\n")
    _unlink_transaction(preset)


def _recover(
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> None:
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)


def recover(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None) -> None:
    """Complete a durable preset transition left by an interrupted writer."""
    _recover(settings_path=settings_path, preset_path=preset_path)


def _settings_generation(path: Path) -> tuple[str | None, tuple[int, int, int, int, int, int] | None]:
    digest, _settings, metadata = _settings_snapshot(path)
    return digest, metadata


def _reservation_active(reservation: _LunaReservation) -> bool:
    with _LUNA_RESERVATIONS_LOCK:
        return _LUNA_RESERVATIONS.get(reservation.preset_path) is reservation


def _reserve_luna_operation(target_settings: Path, target_preset: Path) -> _LunaReservation | None:
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        if _read_preset_unlocked(target_preset) != "luna":
            return None
        generation = (*_settings_generation(target_settings), _read_regular_text(target_preset))
        reservation = _LunaReservation(target_settings, target_preset, generation)
        with _LUNA_RESERVATIONS_LOCK:
            if target_preset in _LUNA_RESERVATIONS:
                return None
            _LUNA_RESERVATIONS[target_preset] = reservation
        return reservation


def _release_luna_operation(reservation: _LunaReservation) -> None:
    with _LUNA_RESERVATIONS_LOCK:
        if _LUNA_RESERVATIONS.get(reservation.preset_path) is reservation:
            del _LUNA_RESERVATIONS[reservation.preset_path]


class _LunaOperation:
    """A reserved Luna call whose model work runs after a short lock gate."""

    def __init__(self, reservation: _LunaReservation) -> None:
        self.reservation = reservation

    def invoke(self, call: object, request: object) -> object | None:
        if not callable(call):
            raise TypeError("Luna provider call is not callable")
        reservation = self.reservation
        result: dict[str, object] = {}
        started = threading.Event()

        with _preset_lock(reservation.preset_path):
            _recover_unlocked(reservation.settings_path, reservation.preset_path)
            if not _reservation_active(reservation) or _read_preset_unlocked(reservation.preset_path) != "luna":
                _release_luna_operation(reservation)
                return None
            current_generation = (*_settings_generation(reservation.settings_path), _read_regular_text(reservation.preset_path))
            if current_generation != reservation.generation:
                _release_luna_operation(reservation)
                return None

            def worker() -> None:
                started.set()
                try:
                    result["value"] = call(request)
                except BaseException as exc:  # propagate provider failures to the hook thread
                    result["error"] = exc

            thread = threading.Thread(target=worker, name="adw-luna-provider", daemon=True)
            thread.start()
            started.wait()

        thread.join()
        error = result.get("error")
        if isinstance(error, BaseException):
            raise error
        return result.get("value")


@contextmanager
def luna_operation(
    *, settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> Iterator[_LunaOperation | None]:
    """Reserve Luna under a short lock; provider work never runs under that lock."""
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    reservation = _reserve_luna_operation(target_settings, target_preset)
    if reservation is None:
        yield None
        return
    try:
        yield _LunaOperation(reservation)
    finally:
        _release_luna_operation(reservation)


def read_preset(
    path: str | Path | None = None,
    *,
    settings_path: str | Path | None = None,
) -> str | None:
    target = _canonical(path) if path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    with _preset_lock(target):
        try:
            _recover_unlocked(target_settings, target)
        except (OSError, ValueError):
            return None
        return _read_preset_unlocked(target)


def _default_preset_unlocked(env: Mapping[str, str], target_preset: Path) -> str:
    explicit = env.get(PRESET_ENV, "").strip()
    if explicit:
        return _validate_preset(explicit)
    haiku_only = env.get(HAIKU_ONLY_ENV, "").strip().lower()
    if haiku_only in {"1", "true", "yes"}:
        return "haiku"
    stored = _read_preset_unlocked(target_preset)
    if stored is not None:
        return stored
    return "haiku" if env.get(REMOTE_ENV) == "true" else "mixed"


def default_preset(
    environment: Mapping[str, str] | None = None,
    *,
    preset_path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> str:
    env = os.environ if environment is None else environment
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    with _preset_lock(target_preset):
        try:
            _recover_unlocked(target_settings, target_preset)
        except (OSError, ValueError):
            pass
        return _default_preset_unlocked(env, target_preset)


def _model_for(preset: str, role: str) -> str:
    if preset == "mixed":
        return "haiku" if role == "comment" else "sonnet"
    if preset == "haiku":
        return "haiku"
    if preset == "sonnet":
        return "sonnet"
    raise ValueError("luna uses command handlers, not a native model")


def _luna_command() -> str:
    return f"ADW_CLAUDE_MANAGED={MANAGED_MARKER} {shlex.quote(str(LUNA_HANDLER_PATH))}"


def comment_prompt(preset: str) -> str:
    _validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's post-write comment verifier.\n"
        "Matching hooks run in parallel. Inspect only the just-written eligible file named by this raw host event; "
        "do not expect another hook to have prepared context and do not duplicate the raw event content. "
        "Use read-only inspection. Do not edit files, settings, or unrelated paths.\n"
        "Parse the hook input supplied after this prompt. If it is empty, malformed, unrelated to a write, "
        "or has no ADW candidate, return exactly {\"ok\": true}.\n"
        "A successful check returns exactly {\"ok\": true}. A failed check returns {\"ok\": false, "
        "\"reason\": \"one bounded remediation instruction\"}.\n"
        "Do not deny or undo the completed write.\n"
        "Hook input: $ARGUMENTS"
    )


def stop_prompt(preset: str) -> str:
    _validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's Stop verifier.\n"
        "Check stop_hook_active before doing any work. If it is true, return exactly {\"ok\": true}. "
        f"Read only the current session's bounded ADW candidate journal by running the exact helper {JOURNAL_READER_PATH} "
        "with the session_id from this hook input as its sole argument. Do not open state files directly, scan "
        "unrelated files, or read files not named by the helper output. "
        "Use read-only inspection. Do not scan unrelated files or edit files or settings.\n"
        "Batch all current prose and document candidates in one review. Empty or malformed ADW-owned input "
        "returns exactly {\"ok\": true}. A clean review returns exactly {\"ok\": true}. A failed review "
        "returns {\"ok\": false, \"reason\": \"one bounded remediation instruction\"}.\n"
        "Use the session_id from this hook input to locate only its journal.\n"
        "Hook input: $ARGUMENTS"
    )


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    selected = _validate_preset(preset)
    if selected == "luna":
        command = _luna_command()
        return {
            "PostToolUse": [{
                "matcher": WRITE_MATCHER,
                "hooks": [{"type": "command", "command": command, "timeout": 120}],
            }],
            "Stop": [{
                "hooks": [{"type": "command", "command": command, "timeout": 120}],
            }],
        }
    return {
        "PostToolUse": [{
            "matcher": WRITE_MATCHER,
            "hooks": [{
                "type": "agent",
                "model": _model_for(selected, "comment"),
                "timeout": 120,
                "prompt": comment_prompt(selected),
            }],
        }],
        "Stop": [{
            "hooks": [{
                "type": "agent",
                "model": _model_for(selected, "document"),
                "timeout": 120,
                "prompt": stop_prompt(selected),
            }],
        }],
    }


def _is_managed_hook(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("type") == "agent":
        prompt = value.get("prompt")
        return isinstance(prompt, str) and prompt.splitlines()[:1] == [MANAGED_MARKER]
    if value.get("type") == "command":
        command = value.get("command")
        if not isinstance(command, str):
            return False
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        return (
            len(parts) == 2
            and parts[0] == f"ADW_CLAUDE_MANAGED={MANAGED_MARKER}"
            and Path(parts[1]).is_absolute()
        )
    return False


def _without_managed(settings: dict[str, Any]) -> dict[str, Any]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    cleaned: dict[str, Any] = dict(settings)
    cleaned_hooks: dict[str, Any] = dict(hooks)
    for lifecycle, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        next_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                next_groups.append(group)
                continue
            remaining = [hook for hook in group["hooks"] if not _is_managed_hook(hook)]
            if len(remaining) == len(group["hooks"]):
                next_groups.append(group)
            elif remaining:
                next_groups.append({**group, "hooks": remaining})
        if next_groups:
            cleaned_hooks[lifecycle] = next_groups
        else:
            cleaned_hooks.pop(lifecycle, None)
    cleaned["hooks"] = cleaned_hooks
    return cleaned


def settings_for_preset(settings: object, preset: str) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("Claude settings must be a JSON object")
    selected = _validate_preset(preset)
    merged = _without_managed(dict(settings))
    hooks = dict(merged.get("hooks")) if isinstance(merged.get("hooks"), dict) else {}
    for lifecycle, groups in generated_hooks(selected).items():
        existing = hooks.get(lifecycle)
        hooks[lifecycle] = list(existing) if isinstance(existing, list) else []
        hooks[lifecycle].extend(groups)
    merged["hooks"] = hooks
    return merged


def _load_settings(path: Path) -> dict[str, Any]:
    return _settings_snapshot(path)[1]


def _atomic_write(path: Path, text: str) -> None:
    target = _lexical(path)
    parent_fd = -1
    try:
        parent_fd = _open_parent(target, create=True)
        leaf = _leaf_lstat(parent_fd, target.name)
        if leaf is not None and stat.S_ISLNK(leaf.st_mode):
            raise ValueError(f"preset state leaf is not a regular file: {target}")
        _atomic_write_regular_open(parent_fd, target.name, leaf, text)
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _atomic_write_settings(
    path: Path,
    text: str,
    *,
    expected_generation: tuple[str | None, tuple[int, int, int, int, int, int] | None] | None = None,
) -> None:
    """Atomically write settings while safely preserving a final settings alias."""
    target = _lexical(path)
    parent_fd = -1
    try:
        parent_fd = _open_parent(target, create=True)
        leaf = _leaf_lstat(parent_fd, target.name)
        if leaf is None or not stat.S_ISLNK(leaf.st_mode):
            _atomic_write_regular_open(
                parent_fd, target.name, leaf, text, expected_generation=expected_generation,
            )
            return
        link_target = os.readlink(target.name, dir_fd=parent_fd)
        resolved_target = _lexical(Path(link_target) if os.path.isabs(link_target) else target.parent / link_target)
        before = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=True)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"preset settings symlink target is not a regular file: {target}")
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
    _atomic_write_regular(resolved_target, text, expected_generation=expected_generation)
    verify_parent = _open_parent(target, create=False)
    try:
        if os.readlink(target.name, dir_fd=verify_parent) != link_target:
            raise ValueError(f"preset settings symlink changed while writing: {target}")
        after = os.stat(target.name, dir_fd=verify_parent, follow_symlinks=True)
        target_parent = _open_parent(resolved_target, create=False)
        try:
            target_after = os.stat(resolved_target.name, dir_fd=target_parent, follow_symlinks=False)
        finally:
            os.close(target_parent)
        if not stat.S_ISREG(after.st_mode) or _metadata_key(after) != _metadata_key(target_after):
            raise ValueError(f"preset settings symlink target changed while writing: {target}")
    finally:
        os.close(verify_parent)


def _atomic_write_regular(
    path: Path,
    text: str,
    *,
    expected_generation: tuple[str | None, tuple[int, int, int, int, int, int] | None] | None = None,
) -> None:
    target = _lexical(path)
    parent_fd = -1
    try:
        parent_fd = _open_parent(target, create=True)
        leaf = _leaf_lstat(parent_fd, target.name)
        _atomic_write_regular_open(parent_fd, target.name, leaf, text, expected_generation=expected_generation)
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _regular_generation(
    parent_fd: int,
    name: str,
) -> tuple[str | None, tuple[int, int, int, int, int, int] | None]:
    descriptor = -1
    try:
        leaf = _leaf_lstat(parent_fd, name)
        if leaf is None:
            return None, None
        if not stat.S_ISREG(leaf.st_mode):
            return "", _metadata_key(leaf)
        descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _LEAF_FLAGS, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        if _metadata_key(opened) != _metadata_key(leaf) or opened.st_size > MAX_STATE_BYTES:
            raise _SettingsChanged(f"settings target changed while writing: {name}")
        data = bytearray()
        while len(data) <= MAX_STATE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_STATE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_STATE_BYTES:
            raise _SettingsChanged(f"settings target changed while writing: {name}")
        after = os.fstat(descriptor)
        if _metadata_key(after) != _metadata_key(opened) or len(data) != after.st_size:
            raise _SettingsChanged(f"settings target changed while writing: {name}")
        return hashlib.sha256(bytes(data)).hexdigest(), _metadata_key(after)
    except (OSError, UnicodeError) as exc:
        raise _SettingsChanged(f"settings target could not be checked while writing: {name}") from exc
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _atomic_write_regular_open(
    parent_fd: int,
    name: str,
    leaf: os.stat_result | None,
    text: str,
    *,
    expected_generation: tuple[str | None, tuple[int, int, int, int, int, int] | None] | None = None,
) -> None:
    temporary_name = ""
    try:
        if leaf is not None and not stat.S_ISREG(leaf.st_mode):
            raise ValueError(f"preset state leaf is not a regular file: {name}")
        mode = leaf.st_mode & 0o777 if leaf is not None else 0o600
        for _attempt in range(32):
            temporary_name = f".{name}.{secrets.token_hex(8)}.tmp"
            try:
                descriptor = os.open(
                    temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _LEAF_FLAGS,
                    mode, dir_fd=parent_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            raise OSError("could not allocate preset state temporary file")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        # Refuse replacing a leaf that changed type while the temporary was written.
        current = _leaf_lstat(parent_fd, name)
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise ValueError(f"preset state leaf is not a regular file: {name}")
        if expected_generation is not None and _regular_generation(parent_fd, name) != expected_generation:
            raise _SettingsChanged(f"settings target changed while writing: {name}")
        os.replace(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _set_preset_unlocked(selected: str, target_settings: Path, target_preset: Path) -> str:
    for _attempt in range(3):
        base_hash, current, base_generation = _settings_snapshot(target_settings)
        base_preset = _read_preset_unlocked(target_preset)
        rendered = json.dumps(settings_for_preset(current, selected), indent=2, sort_keys=True) + "\n"
        transaction = {
            "version": TRANSACTION_VERSION,
            "preset": selected,
            "base_preset": base_preset,
            "base_settings_hash": base_hash,
            "base_settings_metadata": list(base_generation) if base_generation is not None else None,
            "base_managed_hash": _managed_hash(current),
        }
        _atomic_write(
            _transaction_path(target_preset),
            json.dumps(transaction, indent=2, sort_keys=True) + "\n",
        )
        try:
            _atomic_write_settings(
                _canonical(target_settings), rendered,
                expected_generation=(base_hash, base_generation),
            )
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
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        return _set_preset_unlocked(selected, target_settings, target_preset)


def status(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    env = os.environ if environment is None else environment
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        selected = _read_preset_unlocked(target_preset)
        if selected is None:
            selected = _default_preset_unlocked(env, target_preset)
    return {"preset": selected, "settings": str(settings_path or globals()["settings_path"]()), "watch": "settings-only changes are watched automatically; reload plugins after plugin install or source updates"}


def _fallback_after_luna_failure_unlocked(
    role: str,
    reason: str,
    *,
    settings_path: Path,
    preset_path: Path,
) -> dict[str, Any]:
    if role not in {"comment", "prose", "document"}:
        raise ValueError("role must be comment, prose, or document")
    fallback = "mixed"
    current = _read_preset_unlocked(preset_path) or "mixed"
    if current == "luna":
        _set_preset_unlocked(fallback, settings_path, preset_path)
        switched = True
    else:
        fallback = current
        switched = False
    bounded = " ".join(str(reason).split())[:MAX_FAILURE_MESSAGE]
    transition = f"Switched subsequent events to {fallback}." if switched else f"{fallback} remains configured."
    return {
        "preset": fallback,
        "switched": switched,
        "message": f"Luna {role} review unavailable: {bounded}. {transition}",
    }


def fallback_after_luna_failure(
    role: str,
    reason: str,
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> dict[str, Any]:
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        return _fallback_after_luna_failure_unlocked(
            role, reason, settings_path=target_settings, preset_path=target_preset,
        )


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
